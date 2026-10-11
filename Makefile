# `make docs` is the publishing contract: HTML into docs/build/html/, warnings
# as errors, installing only what the docs need. The GitHub Pages workflow
# (.github/workflows/docs.yml) runs exactly this.
.PHONY: docs

docs:
	uv run --frozen --only-group docs sphinx-build -W --keep-going -b html docs docs/build/html

# Regenerate pydantic models from a gateway's OpenAPI spec. Fetch one with
# `dali-iot gateway spec` (writes spec/openapi-<firmware>.json, git-ignored);
# the newest file in spec/ is used unless SPEC= is given.
SPEC ?= $(lastword $(sort $(wildcard spec/openapi-*.json)))
.PHONY: models
models:
	@test -n "$(SPEC)" || { echo "no spec/openapi-*.json; run: dali-iot gateway spec" >&2; exit 1; }
	uv run datamodel-codegen --input $(SPEC) --input-file-type openapi \
	    --output-model-type pydantic_v2.BaseModel --formatters ruff-format \
	    --output src/dali_iot/api_models.py
