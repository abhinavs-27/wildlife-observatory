# Recommended next tasks

In priority order:

1. **When the hardware arrives:** run `scripts/benchmark.py` in the worker container on the Pi.
   Point the Argus at the FTP receiver and confirm its upload format and timestamps. Do a
   72-hour soak test, then fill in [hardware-untestable.md](hardware-untestable.md).
2. **Retention and disk quota:** delete regenerable frames first, then old empty and person-only
   originals, then the oldest unverified animal media above a high watermark. Never delete
   corrected or confirmed media (design §7.8).
3. **Camera-silent alert:** push if no upload has arrived for N hours during expected activity.
   Add it to `background.py`.
4. **Reprocessing:** `POST /api/reprocess {model, scope}` creates scoped runs. Each media item's
   `active_*_run_id` flips only when its cascade completes. Add a Models page in the dashboard.
5. **Mac worker as a launchd agent,** so classification catches up whenever the laptop is home:

   ```xml
   <!-- ~/Library/LaunchAgents/com.wildlife.observatory.worker.plist -->
   <plist version="1.0"><dict>
     <key>Label</key><string>com.wildlife.observatory.worker</string>
     <key>ProgramArguments</key><array>
       <string>/Users/YOU/.local/bin/uv</string><string>run</string>
       <string>--directory</string><string>/Users/YOU/wildlife-observatory/worker</string>
       <string>observatory-worker</string><string>--edge-url</string><string>http://observatory:8000</string>
       <string>--kinds</string><string>classify</string></array>
     <key>EnvironmentVariables</key><dict><key>WORKER_TOKEN</key><string>…</string></dict>
     <key>KeepAlive</key><true/><key>RunAtLoad</key><true/>
   </dict></plist>
   ```

   Pair it with a daily `observatory backup-pull` agent.
6. **Optional LLM analysis:** an Ollama provider behind an `LLMProvider` interface, used only for
   behavior questions, fed only retrieved encounters, and required to cite IDs (design §7.6).
7. **Tracker upgrade:** appearance features from SpeciesNet crops, for better tracks when
   several animals overlap.
8. **Dashboard extras:** a confirm/reject control per detection, video playback with the frame
   scrubber, and individual-animal tagging.
