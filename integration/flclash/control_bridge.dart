// FlClash v0.8.93 integration source. Copy to lib/common/control_bridge.dart.
// Requires the small awaitable-action/proxy patches described alongside it.
// The bridge lives inside the GUI process and never injects desktop input.
import 'dart:async';
import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:math';

import 'package:ffi/ffi.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/core/core.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path/path.dart' as p;
import 'package:win32/win32.dart';

const controlBridgePort = 47892;
const _maxBodyBytes = 8192;
const _maxPendingCommands = 16;

/// Only an explicitly enabled build listens; upstream default is unchanged.
const enableControlBridge = bool.fromEnvironment('FLCLASH_CONTROL');

class ControlBridge {
  HttpServer? _server;
  StreamSubscription<HttpRequest>? _subscription;
  ProviderSubscription<bool>? _tunSubscription;
  Future<void> _pending = Future<void>.value();
  String _token = '';
  int _pendingCount = 0;
  String? _activeAction;
  bool _closing = false;

  Future<void> start() async {
    if (!Platform.isWindows || !enableControlBridge || _server != null) return;
    if (!globalState.container.read(initProvider)) {
      throw StateError('The GUI must finish native initialization first');
    }
    // The GUI may be hidden; keep the native transient authorization state
    // alive across commands instead of reading a newly auto-disposed default.
    _tunSubscription = globalState.container.listen<bool>(
      realTunEnableProvider, (_, _) {}, fireImmediately: true,
    );
    final random = Random.secure();
    _token = base64UrlEncode(List<int>.generate(32, (_) => random.nextInt(256)))
        .replaceAll('=', '');
    final server = await HttpServer.bind(
      InternetAddress.loopbackIPv4,
      controlBridgePort,
      shared: false,
    );
    server.idleTimeout = const Duration(seconds: 10);
    try {
      await _saveEncryptedToken(_token);
      _server = server;
      _subscription = server.listen(
        (request) => unawaited(_handleRequest(request)),
        onError: (Object _) {
          // Neither request bodies nor credentials are logged.
        },
      );
    } catch (_) {
      await server.close(force: true);
      _token = '';
      rethrow;
    }
  }

  Future<void> _handleRequest(HttpRequest request) async {
    try {
      if (_closing) {
        await _reply(request, 503, {'ok': false, 'error': 'bridge_closing'});
        return;
      }
      const expectedHost = '127.0.0.1:$controlBridgePort';
      if (request.headers.value(HttpHeaders.hostHeader) != expectedHost ||
          request.connectionInfo?.remoteAddress.isLoopback != true) {
        await _reply(request, 403, {'ok': false, 'error': 'local_clients_only'});
        return;
      }
      // Browsers cannot call this bridge even from a local page. CLI/MCP
      // clients do not send Origin or Fetch Metadata headers.
      if (request.headers.value('origin') != null ||
          request.headers.value('sec-fetch-site') != null) {
        await _reply(request, 403, {'ok': false, 'error': 'browser_origin_denied'});
        return;
      }
      if (request.method == 'GET' && request.uri.path == '/health') {
        await _reply(request, 200, {
          'ok': true,
          'bridge': 'flclash-gui-control',
          'protocol': 1,
          'pid': pid,
        });
        return;
      }
      if (request.method != 'POST' || request.uri.path != '/command') {
        await _reply(request, 404, {'ok': false, 'error': 'not_found'});
        return;
      }
      final auth = request.headers.value(HttpHeaders.authorizationHeader);
      if (!_constantTimeEqual(auth ?? '', 'Bearer $_token')) {
        await _reply(request, 403, {'ok': false, 'error': 'authentication_failed'});
        return;
      }
      if (request.headers.contentType?.mimeType != 'application/json') {
        await _reply(request, 415, {'ok': false, 'error': 'json_required'});
        return;
      }
      if (request.contentLength < 1 || request.contentLength > _maxBodyBytes) {
        await _reply(request, 413, {'ok': false, 'error': 'invalid_body_size'});
        return;
      }
      final bytes = <int>[];
      await for (final chunk in request.timeout(const Duration(seconds: 5))) {
        bytes.addAll(chunk);
        if (bytes.length > _maxBodyBytes) {
          await _reply(request, 413, {'ok': false, 'error': 'body_too_large'});
          return;
        }
      }
      final body = jsonDecode(utf8.decode(bytes));
      if (body is! Map<String, dynamic> ||
          body.keys.any((key) => key != 'action' && key != 'params') ||
          body['action'] is! String ||
          (body['params'] != null && body['params'] is! Map<String, dynamic>)) {
        await _reply(request, 400, {'ok': false, 'error': 'invalid_command'});
        return;
      }
      final action = body['action'] as String;
      final params = body['params'] as Map<String, dynamic>? ?? {};
      // Read-only snapshots remain available while a native permission or
      // long-running mutation waits. They do not assert mutation completion.
      if (action == 'status') {
        _checkParams(params, const {});
        await _reply(request, 200, {'ok': true, 'data': _status()});
        return;
      }
      if (_pendingCount >= _maxPendingCommands) {
        await _reply(request, 429, {'ok': false, 'error': 'command_queue_full'});
        return;
      }
      final completer = Completer<Map<String, dynamic>>();
      _pendingCount++;
      _pending = _pending.then((_) async {
        try {
          if (_closing) throw const ControlCommandError('bridge_closing');
          _activeAction = action;
          completer.complete(await _dispatch(action, params));
        } catch (error) {
          completer.completeError(error);
        } finally {
          _activeAction = null;
          _pendingCount--;
        }
      });
      // Native authorization may wait for the user. Do not abandon an action
      // with Future.timeout: that would allow a late mutation after failure.
      final result = await completer.future;
      result['operation_pending'] = _pendingCount > 0;
      result['active_action'] = _activeAction;
      result['pending_commands'] = _pendingCount;
      await _reply(request, 200, {'ok': true, 'data': result});
    } on ControlCommandError catch (error) {
      await _reply(request, 409, {'ok': false, 'error': error.code});
    } on FormatException {
      await _reply(request, 400, {'ok': false, 'error': 'invalid_json'});
    } on TimeoutException {
      await _reply(request, 408, {'ok': false, 'error': 'request_body_timeout'});
    } catch (_) {
      // Native exceptions can embed server names/URLs. Return only a stable
      // code, with the GUI's own existing error handling left in place.
      await _reply(request, 500, {'ok': false, 'error': 'native_action_failed'});
    }
  }

  Future<Map<String, dynamic>> _dispatch(
    String action,
    Map<String, dynamic> params,
  ) async {
    final container = globalState.container;
    final setup = container.read(setupActionProvider.notifier);
    if (action == 'status') {
      _checkParams(params, const {});
      return _status();
    }
    if (!container.read(initProvider)) {
      throw const ControlCommandError('gui_not_initialized');
    }
    switch (action) {
      case 'start':
        _checkParams(params, const {});
        if (!container.read(isStartProvider)) {
          await setup.updateStatus(true, strict: true);
        }
        // updateStatus schedules a profile application without awaiting it.
        // It already has the current profile loaded; apply the synchronized
        // GUI settings with the public awaitable method from integration.patch.
        debouncer.cancel(FunctionTag.applyProfile);
        await setup.applyControlUpdate(strict: true);
        await _requireCoreReady();
        if (!container.read(isStartProvider)) {
          throw const ControlCommandError('listeners_did_not_start');
        }
        await _applySystemProxy();
        break;
      case 'stop':
        _checkParams(params, const {});
        debouncer.cancel(FunctionTag.applyProfile);
        await setup.updateStatus(false);
        await _applySystemProxy();
        if (container.read(isStartProvider)) {
          throw const ControlCommandError('listeners_did_not_stop');
        }
        break;
      case 'restart':
        _checkParams(params, const {});
        final wasRunning = container.read(isStartProvider);
        debouncer.cancel(FunctionTag.applyProfile);
        debouncer.cancel(FunctionTag.updateConfig);
        await container.read(coreActionProvider.notifier).restartCoreForControl();
        await _requireCoreReady();
        if (container.read(isStartProvider) != wasRunning) {
          throw const ControlCommandError('restart_state_not_restored');
        }
        await _applySystemProxy();
        break;
      case 'tun':
        _checkParams(params, const {'enabled'});
        final enabled = _boolParam(params, 'enabled');
        container.read(patchClashConfigProvider.notifier).update(
          (state) => state.copyWith.tun(enable: enabled),
        );
        debouncer.cancel(FunctionTag.updateConfig);
        await setup.applyControlUpdate(strict: true);
        await _requireCoreReady();
        if (container.read(realTunEnableProvider) != enabled) {
          throw const ControlCommandError('tun_authorization_or_apply_failed');
        }
        break;
      case 'system_proxy':
        _checkParams(params, const {'enabled'});
        final enabled = _boolParam(params, 'enabled');
        container.read(networkSettingProvider.notifier).update(
          (state) => state.copyWith(systemProxy: enabled),
        );
        await _applySystemProxy();
        break;
      case 'mode':
        _checkParams(params, const {'mode'});
        final value = params['mode'];
        if (value is! String || !Mode.values.any((mode) => mode.name == value)) {
          throw const ControlCommandError('invalid_mode');
        }
        setup.changeMode(Mode.values.firstWhere((mode) => mode.name == value));
        debouncer.cancel(FunctionTag.updateConfig);
        await setup.applyControlUpdate(strict: true);
        await _requireCoreReady();
        break;
      case 'show':
        _checkParams(params, const {});
        await window?.show();
        break;
      case 'exit':
        _checkParams(params, const {});
        if (!await preferences.saveConfig(container.read(configProvider))) {
          throw const ControlCommandError('preference_save_failed');
        }
        final result = _status()..['exit_scheduled'] = true;
        Timer(const Duration(milliseconds: 250), () {
          unawaited(container.read(systemActionProvider.notifier).handleExit());
        });
        return result;
      default:
        throw const ControlCommandError('unknown_action');
    }
    if (!await preferences.saveConfig(container.read(configProvider))) {
      throw const ControlCommandError('preference_save_failed');
    }
    return _status();
  }

  Future<void> _applySystemProxy() async {
    final result = await applySystemProxyState(
      globalState.container.read(proxyStateProvider),
    );
    if (!result) throw const ControlCommandError('system_proxy_apply_failed');
  }

  Future<void> _requireCoreReady() async {
    final container = globalState.container;
    if (container.read(coreStatusProvider) != CoreStatus.connected ||
        !await coreController.isInit) {
      throw const ControlCommandError('native_core_not_ready');
    }
  }

  Map<String, dynamic> _status() {
    final container = globalState.container;
    final patch = container.read(patchClashConfigProvider);
    final network = container.read(networkSettingProvider);
    return {
      'management': 'flclash-gui-actions',
      'pid': pid,
      'initialized': container.read(initProvider),
      'core_status': container.read(coreStatusProvider).name,
      'running': container.read(isStartProvider),
      'system_proxy': network.systemProxy,
      'tun_enabled': patch.tun.enable,
      'tun_authorized': container.read(realTunEnableProvider),
      'mode': patch.mode.name,
      'mixed_port': patch.mixedPort,
      'settings_scope': 'gui-persistent',
      'operation_pending': _pendingCount > 0,
      'active_action': _activeAction,
      'pending_commands': _pendingCount,
    };
  }

  Future<void> close() async {
    _closing = true;
    await _server?.close(force: true);
    await _subscription?.cancel();
    _server = null;
    _subscription = null;
    await _pending;
    _tunSubscription?.close();
    _tunSubscription = null;
    _token = '';
  }
}

class ControlCommandError implements Exception {
  final String code;
  const ControlCommandError(this.code);
}

void _checkParams(Map<String, dynamic> params, Set<String> allowed) {
  if (params.keys.any((key) => !allowed.contains(key))) {
    throw const ControlCommandError('unexpected_parameter');
  }
}

bool _boolParam(Map<String, dynamic> params, String key) {
  final value = params[key];
  if (value is! bool) throw const ControlCommandError('boolean_parameter_required');
  return value;
}

bool _constantTimeEqual(String actual, String expected) {
  final left = utf8.encode(actual);
  final right = utf8.encode(expected);
  var difference = left.length ^ right.length;
  for (var index = 0; index < right.length; index++) {
    difference |= (index < left.length ? left[index] : 0) ^ right[index];
  }
  return difference == 0;
}

Future<void> _reply(HttpRequest request, int status, Map<String, dynamic> data) async {
  try {
    final bytes = utf8.encode(jsonEncode(data));
    request.response.statusCode = status;
    request.response.headers.contentType = ContentType.json;
    request.response.headers.set(HttpHeaders.cacheControlHeader, 'no-store');
    request.response.contentLength = bytes.length;
    request.response.add(bytes);
    await request.response.close();
  } catch (_) {
    // Disconnected clients cannot change command completion semantics.
  }
}

Future<void> _saveEncryptedToken(String token) async {
  final local = Platform.environment['LOCALAPPDATA'];
  if (local == null || local.isEmpty) {
    throw StateError('Windows local application data directory is missing');
  }
  final directory = Directory(p.join(local, 'FlClash-Control'));
  await directory.create(recursive: true);
  final file = File(p.join(directory.path, 'gui-bridge.json'));
  final temporary = File('${file.path}.$pid.tmp');
  final encrypted = _protectForCurrentUser(utf8.encode(token));
  await temporary.writeAsString(jsonEncode({
    'protocol': 1,
    'port': controlBridgePort,
    'pid': pid,
    'protected_token': encrypted.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
  }), flush: true);
  await temporary.rename(file.path);
}

List<int> _protectForCurrentUser(List<int> input) {
  final inputData = calloc<Uint8>(input.length);
  final inputBlob = calloc<CRYPT_INTEGER_BLOB>();
  final outputBlob = calloc<CRYPT_INTEGER_BLOB>();
  try {
    inputData.asTypedList(input.length).setAll(0, input);
    inputBlob.ref.cbData = input.length;
    inputBlob.ref.pbData = inputData;
    final result = CryptProtectData(
      inputBlob, nullptr, nullptr, nullptr, nullptr,
      0x1, outputBlob,
    );
    if (result == 0) throw StateError('Windows credential protection failed');
    return List<int>.from(outputBlob.ref.pbData.asTypedList(outputBlob.ref.cbData));
  } finally {
    inputData.asTypedList(input.length).fillRange(0, input.length, 0);
    if (outputBlob.ref.pbData != nullptr) LocalFree(outputBlob.ref.pbData);
    calloc.free(inputData);
    calloc.free(inputBlob);
    calloc.free(outputBlob);
  }
}
