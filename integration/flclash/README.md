# FlClash 0.8.93 GUI control bridge integration

This source is intended for a local FlClash build. It runs in the GUI process;
the existing GUI, Riverpod state, persistence and Helper/core IPC continue to
own the proxy. No desktop input injection or alternative core host is used.

## Integration

1. Check out the exact `chen08209/FlClash` tag `v0.8.93`.
2. Copy `control_bridge.dart` to `lib/common/control_bridge.dart`.
3. Apply `integration.patch`. It changes six existing Dart files:
   - `ApplicationState` starts the bridge after `globalState.attach()` finishes
     and closes it before disposing the core.
   - `SetupAction.applyControlUpdate()` exposes the existing authorization and
     full core config update as an awaitable operation. GUI debounce calls use
     the same operation. No separate permission bypass is introduced.
   - `common/proxy.dart` provides one serial queue for native system proxy
     changes.
   - `ProxyManager` uses that shared queue; bridge changes can await the same
     native plugin instead of guessing that its asynchronous listener finished.
   - `core/interface.dart` rejects missing native replies instead of treating
     an IPC timeout as a successful listener/configuration action.
   - `core/controller.dart` waits for both configuration and asynchronous
     listener startup, observing errors from both operations. The control-only
     restart path propagates authorization/configuration/startup failures;
     the ordinary GUI retains its existing error presentation.
4. Build with `--dart-define=FLCLASH_CONTROL=true`, in addition to FlClash's
   normal build arguments. Without this flag the bridge is disabled.

## Local API

The listener binds only to `127.0.0.1:47892`. `GET /health` returns bridge name,
protocol and GUI PID, with no credentials. Commands use:

```json
{"action":"tun","params":{"enabled":true}}
```

Supported commands are `status`, `start`, `stop`, `restart`, `tun`,
`system_proxy`, `mode`, `show`, and `exit`. TUN/system proxy accept boolean `enabled`; mode
accepts `rule`, `global` or `direct`. Mutations update real GUI providers and
save the GUI configuration. `show` reveals the existing window; `exit` saves
preferences and schedules the native exit action. Its response is an
acknowledgment; process termination must still be observed. Native authorization remains native, including
any actual permission dialog that the application requires.

Each GUI launch generates a fresh 256-bit random bearer token. Only its
current-user DPAPI ciphertext is written to
`%LOCALAPPDATA%\FlClash-Control\gui-bridge.json`:

```json
{"protocol":1,"port":47892,"pid":1234,"protected_token":"DPAPI_HEX"}
```

A local Python client can use `win32crypt.CryptUnprotectData` on the hex bytes
internally and send `Authorization: Bearer ...`. Never print the plaintext
token, place it in shell arguments, or commit the local state file. The
listener rejects browser Origin/Fetch Metadata headers, incorrect Host,
non-loopback clients, unknown parameters, bodies above 8192 bytes and queues
larger than 16 commands. It does not expose CORS or a general RPC/config API.

## Verification and known integration concern

This directory contains source and a patch; a successful build and runtime
tests are necessary before claiming the bridge is installed or usable.

FlClash's desktop `TunExt.getRealTun` deliberately sets effective
`auto-route=true` and an empty route-address list, even if the serialized
patch stores `auto-route=false`. This explains the observed saved/effective
values and does not require editing the user's route preferences. The
awaitable update uses the same `updateParamsProvider` and therefore retains
this native desktop normalization. Runtime tests must still verify the actual
adapter, routes and unproxied HTTPS traffic, as well as GUI/prefs values.

The response reports configured TUN, native authorization, core readiness and
GUI run state separately. It does not claim external reachability from those
values alone. Test each mutation against its OS/core effect and restoration.
Read-only `status` bypasses the mutation queue and reports `operation_pending`,
`active_action` and `pending_commands`. During a native permission wait, this
is an intermediate snapshot, not confirmation that the queued action finished.

This code imports and integrates with GPL-3.0 FlClash sources; distribution of
the patched GUI must retain the upstream license, notices and corresponding
source obligations. The standalone client can be separately licensed; this
integration patch is an upstream-derived work.
