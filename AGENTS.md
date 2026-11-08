# Container image sources

Containerfiles may use only first-party upstream images or official distribution images.
Do not use arbitrary third-party repackaged images. Pin every base to a digest and
keep its upstream tag so Renovate can propose updates. Verify publisher ownership
before adding a new source; a registry name or digest alone does not prove it.

Keep runtime configuration and secrets out of this public repository.
