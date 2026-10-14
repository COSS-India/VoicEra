# nees-demo runbook — Brazilian Portuguese voice agent on ace-h200

Branch `feat/nees-demo`. Two new Compose projects that share nothing with what
is already running except GPU 1, which they join through the existing MPS
daemon with hard caps:

| Stack | Project | Containers | Host ports (all `127.0.0.1`) |
|---|---|---|---|
| Models | `voicera-nees-demo-models` | `nees_demo_model_{gateway,stt,tts}` | 8400 (gateway) |
| App | `voicera-nees-demo` | `nees_demo_*` + `nees_demo_tunnel` | 3300, 8300, 7960, 9300, 9301, 27318 |

Public access is a temporary Cloudflare URL to the dashboard only.

**Rules for every step**

- Always pass `-p <project>`. A bare `docker compose down` in the wrong folder
  is how you take down someone else's stack.
- Never touch the MPS daemon (`nvidia-cuda-mps-control`), and never run
  `docker system prune`, `docker volume prune` or `down -v` on anything but the
  two projects above.
- The stop button for the whole demo:

  ```bash
  sudo docker compose -p voicera-nees-demo down
  sudo docker compose -p voicera-nees-demo-models down
  ```

Paste the output of each step back into the chat before moving on.

---

## Step 0 — Preflight (read-only)

```bash
# 0.1 The demo gets its own checkout. Nothing runs from production's folder.
git clone -b feat/nees-demo https://github.com/COSS-India/VoicEra.git ~/voicera-nees-demo
cd ~/voicera-nees-demo && git log --oneline -1

# 0.2 GPU 1 headroom and mode. We need ~12 GB and want >15 GB left after.
nvidia-smi -i 1 --query-gpu=index,memory.used,memory.total,compute_mode --format=csv

# 0.3 Which MPS pipe directory production's model containers use. Ours must match.
sudo docker inspect voicera-prod-v2-model-tts \
  --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' | grep -i mps
ls -la /tmp/nvidia-mps-gpu1 2>&1 | head

# 0.4 Our ports are still free (prints nothing if so).
sudo ss -ltn | grep -E ':(3300|8300|7960|9300|9301|27318|8400)\b'

# 0.5 Disk for ~6.5 GB of weights and three new images.
df -h /var/lib/docker ~
```

## Step 1 — Weights

Both repos are public; no token needed.

```bash
cd ~/voicera-nees-demo
sh model-server/stt/pt-whisper/fetch.sh       # ~3.1 GB -> stt/pt-whisper/models/portuguese
sh model-server/tts/pt-chatterbox/fetch.sh    # ~3.2 GB -> tts/pt-chatterbox/checkpoints/portuguese
```

## Step 2 — Model stack

```bash
cd ~/voicera-nees-demo
cp deploy/nees-demo/models.env.example model-server/.env
# If 0.3 showed a pipe directory other than /tmp/nvidia-mps-gpu1, edit MPS_PIPE_DIR.
mkdir -p model-server/.nemo-context
cd model-server

# 2.1 The file list. Expect compose.mps.yml AND both models' compose.extra.yml
#     and compose.mps.yml. No compose.mps.yml means no MPS daemon was detected --
#     stop and tell me, the containers would not get a CUDA context.
FILES=$(sh compose-files.sh); echo "$FILES"

# 2.2 Check the rendered config before starting anything.
sudo docker compose $FILES --project-directory . -p voicera-nees-demo-models config \
  | grep -E 'container_name|device_ids|CUDA_MPS|published|host_ip|^name'
#   want: name voicera-nees-demo-models, nees_demo_model_* names, device_ids "1",
#   CUDA_MPS_PINNED_DEVICE_MEM_LIMIT 0=6G / 0=8G, published 8400 on 127.0.0.1 only.

# 2.3 Build one image at a time (peak disk), then start.
sudo docker compose $FILES --project-directory . -p voicera-nees-demo-models build stt
sudo docker compose $FILES --project-directory . -p voicera-nees-demo-models build tts
nvidia-smi -i 1 --query-gpu=memory.used --format=csv          # BEFORE
sudo docker compose $FILES --project-directory . -p voicera-nees-demo-models up -d

# 2.4 Wait for "ready" in both logs (first start: a few minutes).
sudo docker logs -f nees_demo_model_stt     # Ctrl-C once you see "ready"
sudo docker logs -f nees_demo_model_tts
nvidia-smi -i 1 --query-gpu=memory.used,memory.total --format=csv   # AFTER
sudo docker ps --filter name=voicera-prod-v2 --format '{{.Names}} {{.Status}}'   # prod untouched
```

**Gate:** if GPU 1 has under 15 GB free after this, or any prod container is
not `Up`, run the stop button and paste the output.

```bash
# 2.5 Round trip: TTS speaks Portuguese, STT transcribes it back (upload + live socket).
cd ~/voicera-nees-demo
sudo docker exec -i nees_demo_model_gateway python - < deploy/nees-demo/smoke_pt.py
sudo docker cp nees_demo_model_gateway:/tmp/pt_tts.wav ~/pt_tts.wav   # optional: listen
```

## Step 3 — App stack + tunnel

```bash
cd ~/voicera-nees-demo
cp deploy/nees-demo/app.env.example .env
# Fill the three secrets -- fresh ones, not production's:
python3 - <<'PY'
import base64, os, re, secrets
p = ".env"; s = open(p).read()
for k, v in {"SECRET_KEY": secrets.token_urlsafe(32),
             "INTERNAL_API_KEY": secrets.token_urlsafe(32),
             "PROVIDER_AUTH_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode()}.items():
    s = re.sub(rf"^{k}=.*$", f"{k}={v}", s, flags=re.M)
open(p, "w").write(s); print("secrets written")
PY

APP="-p voicera-nees-demo -f docker-compose.yaml -f deploy/nees-demo/compose.app.yml"

# 3.1 Check before starting.
sudo docker compose $APP config | grep -E '^name|container_name|published|host_ip|MODEL_SERVER'
#   want: nees_demo_* names, 127.0.0.1 on every published port,
#   MODEL_SERVER_URL http://nees_demo_model_gateway:8000/v1 (NOT :8100).

# 3.2 Start.
sudo docker compose $APP up -d --build

# 3.3 The runtime can reach the demo models, by name.
sudo docker exec nees_demo_runtime python -c \
  "import urllib.request; print(urllib.request.urlopen('http://nees_demo_model_gateway:8000/v1/models').read().decode())"

# 3.4 The public URL (changes whenever the tunnel container restarts).
sudo docker logs nees_demo_tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
```

## Step 4 — Browser call

1. Open the tunnel URL, **Sign up** (this is a fresh database), log in.
2. Add your **OpenAI API key** under provider credentials. Portuguese Whisper and
   Portuguese Chatterbox should already show as available — they need no key.
3. Create an agent:
   - Language: **Portuguese (Brazil)**
   - STT: **Portuguese Whisper**, model `pt-whisper`
   - TTS: **Portuguese Chatterbox**, model `pt-chatterbox`, voice `default`
   - LLM: OpenAI, e.g. `gpt-4o-mini`
   - Delivery: **WebSocket — browser test**
   - Prompt, for example:
     > Você é um assistente de voz simpático que fala português do Brasil.
     > Responda sempre em português, em frases curtas e naturais, sem listas
     > nem emojis.
   - Greeting: *Olá! Como posso ajudar você hoje?*
4. Start a test call, allow the microphone, and talk.

Done = the agent greets you, hears you, and answers in Portuguese.

If something fails, paste:

```bash
sudo docker logs --tail 80 nees_demo_runtime
sudo docker logs --tail 40 nees_demo_model_stt
sudo docker logs --tail 40 nees_demo_model_tts
```

## Step 5 — Phone numbers (optional, bring-your-own Vobiz or Plivo)

The provider calls the runtime directly, so it needs its own public URL. The
`voice_tunnel` service in `compose.app.yml` provides one.

```bash
cd ~/voicera-nees-demo
APP="-p voicera-nees-demo -f docker-compose.yaml -f deploy/nees-demo/compose.app.yml"
sudo docker compose $APP up -d voice_tunnel
sleep 10
VOICE_URL=$(sudo docker logs nees_demo_voice_tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)
echo "$VOICE_URL"
sed -i "s#^VOICE_SERVER_BASE_URL=.*#VOICE_SERVER_BASE_URL=$VOICE_URL#" .env
sudo docker compose $APP up -d api arq_worker runtime      # recreate with the new value
curl -s -X POST "$VOICE_URL/answer?agent_id=test&org_id=test" | head -5   # runtime answers publicly
```

Then add the Vobiz/Plivo credentials in the dashboard and attach the number.
The URL is written onto the agent and the provider application when the number
is attached, so **if the voice tunnel restarts, repeat this step and re-attach
the number** -- the old URL stops working. `/answer` and the media socket are
unauthenticated; take the tunnel down when the demo is over.

## Teardown

```bash
sudo docker compose -p voicera-nees-demo down          # app + tunnel
sudo docker compose -p voicera-nees-demo-models down   # models; frees GPU memory
# Add -v to either ONLY to wipe that project's own volumes (demo DB, HF cache).
```
