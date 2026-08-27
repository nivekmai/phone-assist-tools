# Phone Assist Tools

Experimental Home Assistant custom integration for the matching experimental
Home Assistant Android Companion build.

The matching Companion APK is published from the
[nivekmai/android releases](https://github.com/nivekmai/android/releases) page.

It can give the LLM three explicit, independently enabled tools:

- `SetPhoneAlarm(hour, minute, label?)`
- `SetPhoneTimer(duration_seconds, label?)`
- `PlayPhoneMedia(media_type, query?)`

It can also provide device-authorized Google Workspace tools:

- `SearchGmail(query, max_results?)`
- `ReadGmailMessage(id)`
- `SearchGoogleDrive(query, max_results?)`
- `ReadGoogleDriveFile(id)`
- `ListGoogleCalendars(max_results?)`
- `SearchGoogleCalendarEvents(calendar_id?, time_min, time_max, query?, max_results?)`
- `ReadGoogleCalendarEvent(calendar_id?, event_id)`
- `CreateGoogleCalendarEvent(calendar_id?, title, start, end, timezone?, description?, location?)`
- `UpdateGoogleCalendarEvent(calendar_id?, event_id, ...)`
- `DeleteGoogleCalendarEvent(calendar_id?, event_id)`

Google access is optional. Gmail and Drive remain read-only. Calendar access can
read, create, update, and delete events, but this version cannot add attendees
or send invitations. OAuth tokens stay in Home Assistant and are never sent to
the conversation proxy. Only bounded results are returned to the model.

The tools target the Android `mobile_app` device that initiated the Assist
request. A tool is available only when that exact registration advertises the
matching command after the user enables its Companion app toggle. Home
Assistant transports a command to that phone, the phone invokes the Android
Clock or media API locally, and the tool only reports success after the phone
acknowledges the request.

## Request flow

```text
Android Assist request (includes device_id)
  -> integration verifies same user, push support, and per-command opt-in
  -> Home Assistant LLM calls the matching phone tool
  -> mobile_app device notification to that exact device_id
  -> Companion app invokes the matching Android Clock or media API
  -> Companion app calls phone_assist_tools.acknowledge
  -> tool returns success, or raises an error/timeout
```

No Home Assistant timer entity, sentence automation, or hard-coded phone name
is involved in direct LLM tool calls. When Home Assistant handles a timer using
its fast local intent path, the integration wraps Core's existing per-device
mobile timer callback and forwards the `STARTED` event as `command_timer` for an
opted-in phone. Other mobile registrations retain Core's normal Home Assistant
timer notification behavior.

For personal data, the matching app performs this handshake:

```text
Companion registers a non-exportable Android Keystore public key and enabled scopes
  -> server issues a fresh random challenge over the authenticated WebSocket
  -> phone signs challenge + mobile_app webhook ID
  -> server verifies the signature and creates a one-use 20-second grant
  -> first matching Assist context consumes and binds the grant for that pipeline
  -> only that context receives the selected Gmail/Drive/Calendar tools
```

Satellite requests, browser requests, unenrolled phones, expired challenges,
and invalid signatures receive no personal-data tools. Handshake failure does
not fail Assist; it continues normally without those tools.

## Home Assistant compatibility

Home Assistant Core 2026.7 builds the Assist LLM tool list from registered
intent handlers. `__init__.py` therefore registers `SetPhoneAlarm` and
`SetPhoneTimer` intents; the built-in Assist API turns those into LLM tools and
forwards the originating `device_id` to the intent.

The newer Home Assistant API also discovers an integration's `llm.py` platform.
On those versions, `llm.py` contributes only the tools enabled for the
originating registration and uses `LLMContext.device_id`. Keeping both paths
avoids monkey-patching Home Assistant's built-in Assist API.

If Core itself implements either mobile-app phone tool, this compatibility shim
detects the concrete native tool and does not register or contribute a duplicate
for that command. Detection is independent, so an alarm-only Core implementation
can coexist with this shim's timer implementation during migration.

## Install

### HACS custom repository

1. In HACS, open **Integrations**, open the menu, and choose
   **Custom repositories**.
2. Add `https://github.com/nivekmai/phone-assist-tools` with category
   **Integration**.
3. Install **Phone Assist Tools**.
4. Add this top-level key to `/config/configuration.yaml` if it is not already
   present, then restart Home Assistant:

   ```yaml
   phone_assist_tools:
   ```

### Manual

1. Copy `custom_components/phone_assist_tools` into:

   ```text
   /config/custom_components/phone_assist_tools
   ```

2. Add this top-level key to `/config/configuration.yaml`:

   ```yaml
   phone_assist_tools:
   ```

3. Restart Home Assistant Core. This is a YAML-loaded custom integration, so a
   restart is required after first installation or a code update.

4. Keep the built-in **Assist** LLM API enabled for the conversation agent.

5. Install the matching experimental Companion APK. The stock Companion app
   does not implement these command and acknowledgement payloads.

6. In the Companion app, enable the desired alarm, timer, and media controls
   for this server. The permissions are off by default. Changing a toggle
   updates the mobile-app registration.

## Connect Gmail, Google Drive, and Google Calendar

1. In Google Cloud, create or select a project and enable the **Gmail API** and
   **Google Drive API**, and **Google Calendar API**.
2. Configure the OAuth consent screen. While the app remains in testing, add
   your Google account as a test user.
3. Create an OAuth client of type **Web application**. Use the redirect URL
   shown by Home Assistant while adding Phone Assist Tools application
   credentials.
4. In Home Assistant, open **Settings → Devices & services → Application
   credentials**, add the Google OAuth client for **Phone Assist Tools**, then
   add the **Phone Assist Tools** integration and complete Google sign-in.
5. In this Companion build, open **Settings → Companion app → Assist** and
   enable **Read Gmail**, **Read Google Drive**, and/or **Read and write Google
   Calendar** on the phone allowed to authorize those tools.

The OAuth request is limited to `gmail.readonly`, `drive.readonly`,
`calendar.events`, and read-only calendar-list access, plus OpenID email
identity. This version cannot send, delete, archive, upload, edit, or otherwise
mutate email or Drive content. Calendar writes require an explicit user request;
the tools cannot add attendees or send invitations.

## Capability contract

The Companion app advertises the enabled commands in its mobile-app
registration. With all controls enabled, `app_data` contains:

```yaml
supported_device_commands:
  - command_alarm
  - command_timer
  - command_play_media
```

An absent or empty list means neither tool is enabled. Each tool is discovered
and checked again at execution time, so disabling a toggle also rejects a
command that was prepared from an older LLM tool list. Older Core versions
accept and preserve this extra registration field even though only this custom
integration interprets it.

When all Google-access toggles are enabled, `app_data` also contains:

```yaml
assist_personal_data_scopes:
  - gmail_readonly
  - drive_readonly
  - calendar_events_readwrite
assist_personal_data_public_key: <base64 DER P-256 public key>
```

The private key is generated in Android Keystore and cannot be exported by the
app. StrongBox is requested when the device supports it, with normal Android
Keystore as the fallback.

## Command contract

Alarm notification:

```yaml
message: command_alarm
data:
  alarm_hour: 7
  alarm_minute: 30
  alarm_message: Wake up
  alarm_skip_ui: true
  phone_tool_request_id: <unique request id>
```

Timer notification:

```yaml
message: command_timer
data:
  timer_seconds: 300
  timer_message: Tea
  timer_skip_ui: true
  phone_tool_request_id: <unique request id>
```

Media notification:

```yaml
message: command_play_media
data:
  media_type: audiobook # or music
  media_query: My Supermix # optional; omitted when resuming
  phone_tool_request_id: <unique request id>
```

The tools set `*_skip_ui` to `true`. Android still routes the request through
the public Clock intent API, but a compatible Clock app creates the alarm or
timer without opening its main UI.

After attempting the Clock intent, the app must call:

```yaml
action: phone_assist_tools.acknowledge
data:
  request_id: <phone_tool_request_id>
  success: true
```

For a rejected command it calls the same action with `success: false` and an
optional `error` string.

## Validation and limits

- Alarm time is validated as a 24-hour local-phone time: hour `0..23`, minute
  `0..59`.
- Timer duration is validated as `1..86400` seconds (up to one day), matching
  the Companion command receiver.
- Labels are optional, trimmed, and limited to 200 characters.
- A command waits 12 seconds for an acknowledgement.
- Multiple simultaneous requests are isolated by request ID, and all pending
  state is cleaned up after success, failure, cancellation, or timeout.
- Request IDs are fresh server-generated ULIDs; model-supplied tool-call IDs
  are never reused as acknowledgement credentials.
- Tool discovery and dispatch require the originating device registration and
  Assist context to belong to the same Home Assistant user.
- The acknowledgement must be called by that same user. The opaque request ID
  prevents unrelated calls from resolving a pending command.

## Caveats

- A positive acknowledgement means the Companion app successfully dispatched
  the Android Clock intent. Android does not provide a standard cross-clock-app
  API to query the newly created alarm or timer afterward.
- Delivery still depends on the Companion app's configured local or remote push
  channel.
- On Home Assistant 2026.7, registered intent definitions may be global to the
  built-in Assist API. A disabled intent can therefore remain visible to the
  model on that compatibility path, but call-time gating rejects it without
  operating the phone. Direct `llm.py` discovery fully hides disabled tools.
- A call made without an originating mobile-app `device_id`, same-user context,
  advertised capability, or usable push path fails safely instead of choosing
  another phone.
- Personal-data search results are limited to 10 items and individual textual
  reads to 12,000 characters. Binary Drive files are not downloaded into the
  model context; the tool returns metadata and a link instead.
- Retrieved email, file, and calendar content is untrusted data. The LLM prompt
  explicitly tells the model never to follow instructions contained inside it.
- Calendar search is capped at 10 events. Create/update/delete tools are exposed
  only in the same phone-signed context and their descriptions require an
  explicit user request for the exact write. Deletion must never be inferred.
- The acknowledgement action is available to authenticated Home Assistant
  clients. Its unguessable request ID and same-user check prevent accidental
  cross-talk, but this is not cryptographic device attestation.
- The integration intentionally uses the Mobile App device-action function.
  That is the only current path that preserves the exact device ID while also
  carrying arbitrary command data through the legacy mobile notification
  transport. It is a Home Assistant internal API and should be rechecked during
  major Core upgrades.

## Migration

- The updated Companion app can keep accepting `phone_tool_request_id` and
  calling `phone_assist_tools.acknowledge` on older Core installations.
- On a Core installation with the native protocol, the app instead receives a
  `hass_command_id` and reports `mobile_app/command_result`. No server-version
  guess is required; the correlation field identifies the protocol.
- Once Core provides both native tools and all clients have upgraded, remove
  `phone_assist_tools:` from `configuration.yaml`, remove this custom component,
  and restart Home Assistant. Until then, the native-tool detection prevents
  duplicate tools if the shim remains installed.

## Local package validation

Run:

```bash
python3 validate_package.py
```

This checks Python syntax, manifest JSON, required files, and the shared payload
contract without requiring a full Home Assistant development environment.
