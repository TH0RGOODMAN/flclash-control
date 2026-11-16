import 'dart:async';

import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCore extends Mock implements CoreHandlerInterface {}

const params = SetupParams(selectedMap: {}, testUrl: 'https://example.com');
const state = SetupState(
  profileId: null,
  profileLastUpdateDate: null,
  overwriteType: OverwriteType.standard,
  rules: [],
  proxyGroups: [],
  addedRules: [],
  script: null,
  overrideDns: false,
  dns: Dns(),
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late MockCore core;
  late CoreController controller;

  setUp(() {
    core = MockCore();
    controller = CoreController.test(core);
  });

  test('setup completion awaits asynchronous listener startup', () async {
    final listener = Completer<void>();
    when(() => core.setupConfig(params)).thenAnswer((_) async => '');
    var completed = false;
    final operation = controller
        .setupConfig(
          params: params,
          setupState: state,
          preloadInvoke: () => listener.future,
        )
        .then((value) {
          completed = true;
          return value;
        });
    await Future<void>.delayed(Duration.zero);
    expect(completed, isFalse);
    listener.complete();
    expect(await operation, '');
  });

  test(
    'listener error waits for and observes concurrent setup error',
    () async {
      final setup = Completer<String>();
      final listener = Completer<void>();
      when(() => core.setupConfig(params)).thenAnswer((_) => setup.future);
      final operation = controller.setupConfig(
        params: params,
        setupState: state,
        preloadInvoke: () => listener.future,
      );
      final verification = expectLater(operation, throwsStateError);
      listener.completeError(StateError('listener failed'));
      await Future<void>.delayed(Duration.zero);
      setup.completeError(StateError('setup failed'));
      await verification;
    },
  );

  test(
    'synchronous listener failure is reported without losing setup result',
    () async {
      when(() => core.setupConfig(params)).thenAnswer((_) async => '');
      await expectLater(
        controller.setupConfig(
          params: params,
          setupState: state,
          preloadInvoke: () => throw StateError('listener failed'),
        ),
        throwsStateError,
      );
    },
  );

  test(
    'setup failure also waits for asynchronous listener completion',
    () async {
      final listener = Completer<void>();
      when(
        () => core.setupConfig(params),
      ).thenAnswer((_) async => throw StateError('setup failed'));
      var completed = false;
      final operation = controller.setupConfig(
        params: params,
        setupState: state,
        preloadInvoke: () => listener.future,
      );
      final verification = expectLater(
        operation.whenComplete(() => completed = true),
        throwsStateError,
      );
      await Future<void>.delayed(Duration.zero);
      expect(completed, isFalse);
      listener.complete();
      await verification;
    },
  );
}
