# second-brain inbox

Where captures wait before a [second-brain](https://github.com/albegosu/second-brain)
worker files them into your wiki. The capture page writes one JSON file per
capture into `queue/`; `.github/workflows/capture.yml` files them into the wiki
repository and empties the queue.

**Keep this repository private.** The capture token on your devices can write
here and nowhere else; the wiki is written with a deploy key stored in this
repository's secrets. Both are created by the engine's `bin/setup`.
