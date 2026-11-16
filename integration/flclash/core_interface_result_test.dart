import 'dart:async';

import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

class ResultCore extends CoreHandlerInterface {
  ResultCore(this.result);

  final String? result;

  @override
  final Completer<void> completer = Completer<void>()..complete();

  @override
  Future<T?> invoke<T>({
    required ActionMethod method,
    dynamic data,
    Duration? timeout,
  }) async => result as T?;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

const update = UpdateParams(
  tun: Tun(),
  mixedPort: 7890,
  allowLan: false,
  findProcessMode: FindProcessMode.off,
  mode: Mode.rule,
  logLevel: LogLevel.error,
  ipv6: false,
  tcpConcurrent: false,
  externalController: ExternalControllerStatus.close,
  unifiedDelay: false,
);
const setup = SetupParams(selectedMap: {}, testUrl: 'https://example.com');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('updateConfig rejects a missing native response', () async {
    expect(ResultCore(null).updateConfig(update), throwsStateError);
  });

  test('setupConfig rejects a missing native response', () async {
    expect(ResultCore(null).setupConfig(setup), throwsStateError);
  });

  test('updateConfig preserves the successful empty native result', () async {
    expect(await ResultCore('').updateConfig(update), '');
  });

  test('setupConfig preserves the successful empty native result', () async {
    expect(await ResultCore('').setupConfig(setup), '');
  });

  test('updateConfig preserves an explicit native error result', () async {
    expect(await ResultCore('failed').updateConfig(update), 'failed');
  });

  test('setupConfig preserves an explicit native error result', () async {
    expect(await ResultCore('failed').setupConfig(setup), 'failed');
  });
}
