# Real authorized CTF test checklist

This is the only manual test sequence needed after the Draft PR is reviewed.
Do not send the API Key to the developer Agent; enter it only in the local UI.

## Before starting

- [ ] Use a Windows account you control; the API Key is DPAPI-encrypted for that account.
- [ ] Start the local workbench from the reviewed branch.
- [ ] Do not expose the ports to the public internet or an untrusted LAN.
- [ ] Use only a challenge you are authorized to test.
- [ ] Network remains off until you explicitly enable it.

## First run

- [ ] Open the workbench and go to 模型服务设置.
- [ ] Enter your own DeepSeek API Key; do not paste it into chat, logs or Git.
- [ ] Keep or edit the default `DeepSeek-V4.1-Flash` (API ID `deepseek-flash`) and save.
- [ ] Confirm the page shows only masked status, never the full Key.
- [ ] Confirm 联网调用 is still off immediately after saving.
- [ ] Enable 联网调用 and save the switch only when ready.
- [ ] Run the fixed synthetic connection test once; it sends only the fixed synthetic prompt.

## Real challenge loop

- [ ] Create an A2 challenge with a synthetic or authorized real challenge archive.
- [ ] Import the archive; verify the app reports its original entries separately from the generated manifest.
- [ ] Ask one focused analysis question; verify the answer and call audit appear.
- [ ] If the model proposes a read-only tool:
  - [ ] Verify it is pending and cannot execute before approval.
  - [ ] Approve it; confirm approval alone does not execute it.
  - [ ] Explicitly execute it; confirm the output Artifact is stored.
  - [ ] Ask the next question; confirm the previous tool result is visible to the model.
- [ ] Verify the Writeup matrix: each item is proven, missing with remediation, or N/A with a reason.
- [ ] Confirm the human Writeup draft is never silently overwritten; save a human edit and reload it.
- [ ] Generate the Writeup preview and export the evidence ZIP.
- [ ] Verify the ZIP includes `writeup.md` (human or clearly labelled generated fallback), `writeup_generated.md` (when generated), `manifest.json`, `SHA256SUMS` and import ownership metadata.
- [ ] Verify `SHA256SUMS` and ZIP CRC; verify the human draft bytes match the exported `writeup.md`.
- [ ] Record observations; do not invent a Flag or platform verification.

## Boundaries

- [ ] No real Flag is required for a synthetic run; absence is reported as missing, not fabricated.
- [ ] No real target is scanned or attacked.
- [ ] No automatic tool execution, automatic Flag submission or public deployment is expected.
- [ ] Stop and report a BLOCKED condition if the real provider is unavailable; do not treat Mock/CI as real API validation.
