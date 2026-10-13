.PHONY: run ui test test-ui test-all lint migrate eval update-readme

run:
	.venv/bin/uvicorn app.main:app --reload --port 8000

ui:
	cd web && npm run dev

test:
	.venv/bin/pytest -q

test-ui:
	cd web && npm test

test-all:
	.venv/bin/pytest -q
	.venv/bin/ruff check .
	cd web && npm test

lint:
	.venv/bin/ruff check .

# Apply migrations/*.sql to DATABASE_URL (the API also does this on start-up).
migrate:
	.venv/bin/python -m app.migrate

# Run RAGAS evaluation against the golden dataset.
eval:
	@if [ -z "$(DOC_ID)" ]; then \
		echo "ERROR: DOC_ID is not set.  Run: DOC_ID=<your_doc_id> make eval"; \
		exit 1; \
	fi
	.venv/bin/python eval/run.py --doc-id $(DOC_ID)

# Refresh README.md scores from the latest file in eval/results/ (no eval run needed).
update-readme:
	.venv/bin/python eval/run.py --update-readme
