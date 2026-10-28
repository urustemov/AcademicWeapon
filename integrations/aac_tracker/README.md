# AAC Tracker portal bridge

The portal renders AAC Tracker natively and keeps Google Sheets as the source
of record. `API_EXTENSION.gs` is added to the existing Apps Script project; it
does not replace `Code.gs` or `Index.html`.

## One-time setup

1. Add `API_EXTENSION.gs` to the current Apps Script project.
2. Add Script property `AAC_TRACKER_API_KEY` with a long random value.
3. Deploy a new Web App version that executes as the project owner and accepts
   requests without an interactive Google login. The API still requires the
   secret and accepts only the four emails already listed in `CONFIG.ALLOWED_USERS`.
4. Store the same secret in Render as `AAC_TRACKER_API_KEY`.
5. Store the deployment URL in Render as `AAC_TRACKER_API_URL`.

`Code.gs` and `Index.html` remain unchanged. During a validated portal request,
the extension temporarily supplies the already allowlisted Advising Team actor
to the existing functions and restores the original access check afterwards.

The browser never receives the secret. All Tracker browser requests go to the
portal, which enforces the `advising_team` role and CSRF protection before the
server calls Apps Script.
