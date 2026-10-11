# BinThere AI Waste Assistant integration

Implemented on `feature/ai-assistant`. The branch was checked before edits; no branch switches, merges or resets were performed. The existing navigation system, optimizer, local OSM dataset and Mapbox routing remain in place.

## Reference implementation and adapted logic

The reference standalone page accepts file selection, image drops and clipboard images. FileReader creates a data URL; an Image and canvas shrink the longest side to 1024 pixels, flatten transparency onto white and encode JPEG at quality 0.8. It can instead send some undecodable original formats. Optional question and city/ZIP are appended to a prompt requesting up to eight identified items, materials, disposal categories, preparation steps, tips, a direct answer and uncertainty. Browser JavaScript calls Gemini with inline base64 image bytes and a hard-coded key. It retries a rejected thinking option without that option, and retries once for malformed/missing answers. It extracts a JSON object from returned text and renders cards using textContent. Its weaknesses include the exposed key, instructions to guess unclear objects, user instructions mixed into the same prompt, limited response validation, and silently treating unrecognized categories as landfill.

BinThere adapts the workflow, image resizing/compression, optional multimodal inputs, bounded malformed-output retry, multi-item cards, colors and textContent rendering. It uses object URLs and JPEG Blobs in the browser instead of retaining base64 data URLs. Base64 conversion happens only in the backend for Gemini. The standalone HTML and exposed key were not copied. HEIC and other unsupported formats are explicitly rejected rather than sending undecoded content.

## Implemented behavior

- Smart Navigation and AI Waste Assistant tabs share the existing BinThere panel and design. Switching views preserves the Mapbox instance, starting location, destination, route layers and AI results. Pending map selection is canceled when entering AI view. Keyboard tab navigation and mobile layouts are supported.
- File selection, drag-and-drop and clipboard image paste (only in the AI tab); preview, replacement and removal; JPEG/PNG/WebP validation; 8 MB file and 20-megapixel limits; 1024-pixel browser resizing with white transparency background and JPEG quality 0.8.
- Text-only, image-only and combined requests; optional city/ZIP; Enter submission with Shift+Enter newline and IME support. Questions are limited to 2,000 characters and location to 120.
- Loading/processing states, duplicate-submit prevention, cancellation, timeout handling, stale-response invalidation on input changes, readable errors and manual retry. Local API requests time out after 270 seconds, allowing the model lookup and bounded malformed-output retry; provider calls have a 5-second connect limit, a 30-second model-lookup read limit and a 100-second analysis read limit. Provider quota/auth/network errors are not automatically retried. Malformed or truncated generated guidance is retried once.
- Strict response validation on both server and frontend, up to eight objects, all requested disposal categories including `unknown`, preparation steps, tips, direct answer, uncertainty and honest empty results. Invalid categories never silently become landfill. Unsafe ordinary-bin recommendations for recognized special-waste terms are rejected server-side and blocked from navigation actions client-side.
- A system instruction separates the response/safety contract from untrusted question, photo and city. It requires clear recognition rather than confident guessing and says local rules have not been verified. It requests conservative hazardous-waste handling and forbids inventing facilities. Model behavior is not a guarantee of factual correctness.
- Recycling recommendations offer **Find recycling locations**; ordinary nonhazardous landfill recommendations offer **Find trash bins**. Actions switch tabs and select the existing facility filter, retaining the user's start/destination/route and using already loaded OSM results. With no start, the user is prompted to choose one; existing discovery then applies that filter. No new location database or facility coordinates come from AI.
- Recycling actions explicitly disclose that mapped locations may not accept the suggested material. Hazardous waste, batteries, e-waste, compost, donation, special drop-offs and unknown items do not link to generic bins; the UI says no verified appropriate disposal location is currently available. Generic OSM recycling points are not treated as verified specialty collection sites.

## Files

New:

- `backend/ai_models.py`: strict Pydantic request-result contract and special-waste consistency check.
- `backend/gemini_service.py`: image decoding, safe JPEG normalization, Gemini configuration/model check, structured-output requests, error mapping, bounded retry and two-call concurrency limit.
- `backend/tests/test_ai_assistant.py`: deterministic API/provider-boundary tests.
- `frontend/src/ai_assistant.js`: modular upload, request, tabs and result controller.
- `frontend/src/ai_assistant.css`: scoped green-and-white assistant UI styles.
- `frontend/src/ai_state.js`: shared file, sizing, result-validation and navigation-action helpers.
- `frontend/tests/ai_state.test.js`, `frontend/tests/browser/ai.spec.js`: frontend unit and browser coverage.
- `AI_ASSISTANT_REPORT.md`: this report.

Modified:

- `backend/main.py`: bounded multipart AI endpoint; existing routes preserved.
- `backend/requirements.txt`: Pillow and python-multipart.
- `backend/.env.example`: server-only Gemini configuration.
- Local ignored `backend/.env`: blank Gemini key and configurable default model, preserving existing Mapbox/settings.
- `frontend/index.html`: tabs, navigation wrapper and separate AI panel/IDs.
- `frontend/src/script.js`: assistant initialization and existing-filter callback.
- `frontend/package.json`: unit-test command includes the added test module.
- Root `README.md`: setup, usage and provider documentation.

## API and credential configuration

`POST /ai/analyze`, **multipart/form-data**:

- `question`: optional string, max 2,000 characters.
- `place`: optional city/ZIP string, max 120 characters.
- `image`: optional JPEG/PNG/WebP file, max 8 MB and 20 megapixels.
- At least an image or nonblank question is required. Full request body is bounded to 8 MB + 64 KiB, including multipart overhead.

Successful JSON preserves the reference structure:

```json
{
  "answer": null,
  "summary": "A plastic bottle.",
  "items": [{
    "name": "Plastic bottle", "material": "PET plastic", "bin": "recycling",
    "steps": ["Empty it and confirm local acceptance."], "tip": null
  }],
  "unsure": "Municipal rules have not been verified."
}
```

This example describes the schema, not a claimed live model response. Categories: `recycling`, `compost`, `landfill`, `hazardous`, `ewaste`, `donate`, `dropoff`, `unknown`. All fields are required; answer, tip and unsure may be null. Invalid fields, types, categories and extra properties fail validation. Empty items is valid for a general question or an unrecognizable image.

Error status codes: 422 missing/invalid input or blocked output, 413 too large, 415 unsupported MIME, 429 provider quota or local concurrency limit, 503 missing/rejected credentials or unavailable model, 504 provider timeout, 502 network/provider/malformed-output failure. Errors do not include provider bodies, keys, photos or user questions. No uploaded images are permanently retained. The backend validates actual decoded format against declared MIME, checks pixels, applies EXIF orientation, strips metadata and re-encodes to JPEG before transmitting to Google. Browser text discloses that the supplied image/question are sent to Gemini.

Configure **a fresh private key** only in `backend/.env`:

```dotenv
GEMINI_API_KEY=YOUR_NEW_PRIVATE_KEY
GEMINI_MODEL=gemini-3.8-flash
```

The key in the supplied reference is exposed: revoke/replace it rather than reusing it. Never add a Gemini key to `frontend/.env`, a `VITE_` variable, HTML or browser code. Backend errors/logs do not print keys. Real `.env` files remain ignored by Git. Configuration changes require restarting FastAPI.

The default model was checked against Google's official [Gemini 3.8 Flash model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), which lists image/text input and structured outputs. The implementation follows the current [structured-output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output) and [GenerateContent API reference](https://ai.google.dev/api/generate-content), using `generationConfig.responseFormat.text` with a JSON Schema. Before generation, the backend checks the configured model via [models.get](https://ai.google.dev/api/models); successful model capability checks are cached for one hour by model/key hash. Account/model availability and quota still require valid credentials. Custom models must support image input and structured text output; unsupported configuration returns a safe provider error.

## Tests and verification

Commands:

```sh
.venv/bin/python -m unittest discover -s backend/tests
npm --prefix frontend test
npm --prefix frontend run test:browser
npm --prefix frontend run lint
npm --prefix frontend run build
```

**Final results: 128 backend tests, 13 frontend unit tests and 46 Chrome browser tests passed. Lint and production build passed; `git diff --check` passed.** This includes all 113 earlier backend tests and all 30 earlier browser tests. Deterministic tests use explicit mock Gemini responses and an in-browser map adapter; navigation integration retains its existing FastAPI tests. They do not claim actual AI recognition or live Gemini success. Coverage includes uploads and compression, text/image combinations, multiple objects, unknown/hazardous guidance, empty results, invalid JSON/schema/categories, unsupported/corrupt/mismatched/oversized images, body limits, missing/rejected keys, model checks, rate limits, provider timeout/network failure, bounded retries, concurrency limits, upload/drop/paste, duplicate prevention, cancellation and stale results, tab switching, AI-to-navigation filters, route preservation, safe rendering, mobile layout and all earlier navigation tests.

### Live credential check

No private `GEMINI_API_KEY` is configured in this workspace or inherited environment. No requests were sent to Gemini and the exposed reference key was not tried. A real request against the running backend was made:

```sh
curl -X POST http://127.0.0.1:8000/ai/analyze \
  -F 'question=How should I dispose of a clean plastic water bottle?'
```

Observed **HTTP 503** with the intended safe configuration message: `AI Assistant is not configured. Add GEMINI_API_KEY to backend/.env and restart the backend.` Therefore real Gemini recognition remains unverified, not a fabricated success. The existing running `/resources?latitude=40.53399&longitude=-74.45793&radius=16093&include_metadata=true` endpoint was also checked after integration: HTTP 200, local_first, full coverage, all 273 genuine saved records. After adding a fresh key, run one limited smoke test:

```sh
curl -X POST http://127.0.0.1:8000/ai/analyze \
  -F 'question=How should I dispose of a clean plastic water bottle?' \
  -F 'place=Piscataway, NJ'
# For one photo test, supply a real image:
curl -X POST http://127.0.0.1:8000/ai/analyze \
  -F 'question=Identify recognizable items and give general disposal guidance.' \
  -F 'image=@/absolute/path/to/your/photo.jpg;type=image/jpeg'
```

## Run the combined app

From repository root:

```sh
.venv/bin/python -m pip install -r backend/requirements-dev.txt
# Edit backend/.env with a NEW Gemini key; retain existing Mapbox settings.
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open http://localhost:5173, choose **AI Waste Assistant**, upload a supported photo or ask a question, then use a disposal action to return to navigation. `FACILITY_DATA_MODE=local_first`/`local_only` and the existing genuine 10-mile dataset still work; Mapbox routing remains separate and live. Do not launch a second backend on port 8000 while an existing one is running; restart the existing process to load changed environment settings.

## Remaining limitations

Live AI requires a fresh Gemini key and model/account access and was not tested without them. Model instructions, schema validation and conservative navigation checks reduce unsafe outputs but cannot prove identification correctness or verify local regulations. Specialty facility acceptance/public access is unverified; no specialty navigation shortcut is offered. No HEIC/GIF/SVG support; convert to JPEG/PNG/WebP first. Cancellation prevents stale browser rendering but cannot abort a synchronous provider request already running in FastAPI. The two-call concurrency guard and model cache are per-process, not shared across workers. The existing large Mapbox bundle build advisory remains. No branches were merged.

## Follow-up: live Gemini request-format correction

After credentials were configured, a controlled live diagnostic found:

- Model lookup (`GET /v1beta/models/gemini-3.8-flash`): **HTTP 200**.
- Original GenerateContent POST: **HTTP 400 / INVALID_ARGUMENT** at `generation_config.response_format.text.mime_type`, rejecting `application/json`.
- Cause: the GenerateContent REST `TextResponseFormat.mimeType` field is an enum, unlike the MIME string used in SDK/Interactions examples. The correct REST value is **`APPLICATION_JSON`**. See [the official TextResponseFormat API reference](https://ai.google.dev/api/generate-content#TextResponseFormat).

Changed only the output format enum in `backend/gemini_service.py` and strengthened the existing mocked payload test to assert its exact value. All **128 backend tests pass** after the correction. A limited live call through the actual service returned a Pydantic-validated result identifying **Plastic water bottle → recycling**. This supersedes the earlier integration-time statement that no live Gemini result had been tested. No private keys, image bytes or user questions were logged. Live photo recognition is still not established by this text-only smoke test.

The running FastAPI endpoint was also verified after automatic reload: `POST http://127.0.0.1:8000/ai/analyze` returned **HTTP 200** with **Plastic water bottle → recycling** using live Gemini.


## Follow-up: browse the closest recycling location for battery results

At the user's request, battery/hazardous/e-waste/special-drop-off recommendations now offer **Find nearby recycling centers**, even when no battery-specific OSM tags exist. This supersedes the original stricter specialty-navigation behavior above. The action browses general mapped locations, never claims acceptance, and displays a contact-operator warning in both the AI card and selected facility details. Batteries are still not recommended for ordinary bins, and the backend's hazardous-disposal response validation remains intact.

The handoff searches the existing `/resources` API once within 16,093 meters of the retained start, displays real recycling locations and selects the closest by straight-line distance excluding explicitly private/no-access records. It preserves start, destination and existing route layers. Loading/failure/partial-coverage cases remain explicit and stale responses do not focus an obsolete location. Users can select walking directions from the focused facility's details.

An actual API check from the approximate configured center (`40.53399, -74.45793`) returned HTTP 200, full coverage and **85 genuine recycling locations**. Closest was **Piscataway Recycling Center, node/670492097, approximately 1,099 meters away**. This is a real saved OSM listing, not verified battery acceptance or walking distance. The previous default 1-kilometer search excluded it. No public Overpass or Gemini requests were necessary for this check.
