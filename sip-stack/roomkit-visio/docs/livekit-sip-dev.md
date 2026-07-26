# livekit-sip (local build)

`compose.yml` runs `image: livekit-sip:local`, built by `make sip-build` from `$LIVEKIT_SIP_SRC`.

## Build prerequisites

- GStreamer **1.28.1** (build + runtime, inside the image).
- Go **1.25.0**, `pkg-config`, `libopus-dev`, `libopusfile-dev`, `libsoxr-dev`.

## Source layout

```
parent/
├── roomkit-visio/    # this repo
└── livekit-sip/      # https://github.com/suitenumerique/livekit-sip @ branch sip-video-v2
```

Clone:

```sh
git clone -b sip-video-v2 https://github.com/suitenumerique/livekit-sip.git ../livekit-sip
```

Override the path with `LIVEKIT_SIP_SRC` (per-command or in `.env`):

```sh
LIVEKIT_SIP_SRC=path/to/livekit-sip make sip-build
```

## Workflow

```sh
make sip-build       # docker build livekit-sip:local from $LIVEKIT_SIP_SRC
make sip-rebuild     # build + force-recreate the running container
make logs SVC=livekit-sip
```

`make bootstrap` calls `sip-build`.

## Targets

| Target | Action |
| --- | --- |
| `make sip-build` | `docker build -f $LIVEKIT_SIP_SRC/build/sip/Dockerfile -t livekit-sip:local $LIVEKIT_SIP_SRC` |
| `make sip-rebuild` | `make sip-build` + `docker compose up -d --force-recreate livekit-sip` |

## Build internals

```
docker build \
  -f $LIVEKIT_SIP_SRC/build/sip/Dockerfile \
  -t livekit-sip:local \
  $LIVEKIT_SIP_SRC
```

Two-stage Go build: compiles `cmd/livekit-sip/main.go` against `pkg/`, `res/`, `version/`, then ships the binary in a Go runtime base. Builder installs `pkg-config libopus-dev libopusfile-dev libsoxr-dev`; runtime installs `libopus0 libopusfile0 libsoxr0`.

## GStreamer pipeline dumps

Set `gst.dump_dot: true` in `docker/livekit-sip/config/livekit-sip.yaml` to make livekit-sip write a Graphviz `.dot` file for each pipeline state change. Container path `/tmp/gst-dots` is bind-mounted to `./gst-dots/` on the host.

Each `.dot` file is one pipeline at a given state transition: elements, pads, negotiated caps, queues, buffer occupancy. Filenames look like `0.00.00.123456789-pipeline-name-READY_PAUSED.dot` (wall-clock offset + state change). Render with `dot -Tpng <file>.dot -o <file>.png` if Graphviz is installed.

```sh
# After flipping gst.dump_dot to true:
docker compose up -d --force-recreate livekit-sip
# Reproduce the issue
ls gst-dots/
# Wipe dumps
make gst-clear
```

`gst-dots/` is gitignored (only `.gitkeep` tracked). `gst.gst_debug` in the same YAML sets GStreamer log verbosity; output goes to `make logs SVC=livekit-sip`.

## Troubleshooting

- **`docker build` fails on Go modules** — `go mod download` in `$LIVEKIT_SIP_SRC` first.
- **`unrecognized config field`** — sync `docker/livekit-sip/config/livekit-sip.yaml` with the branch's schema.
- **Container keeps the old binary after a build** — use `make sip-rebuild`. `make restart` does not pick up a new image.
