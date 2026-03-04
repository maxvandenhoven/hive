.PHONY: install-pre-commit
install-pre-commit:
	@pre-commit install
	@pre-commit install --hook-type commit-msg


.PHONY: sync-all
sync-all:
	@$(MAKE) --no-print-directory --directory=packages/hive-agents sync
	@$(MAKE) --no-print-directory --directory=packages/hive-engine sync
	@$(MAKE) --no-print-directory --directory=services/hive-api sync


.PHONY: format-all
format-all:
	@$(MAKE) --no-print-directory --directory=packages/hive-agents format
	@$(MAKE) --no-print-directory --directory=packages/hive-engine format
	@$(MAKE) --no-print-directory --directory=services/hive-api format


.PHONY: lint-all
lint-all:
	@$(MAKE) --no-print-directory --directory=packages/hive-agents lint
	@$(MAKE) --no-print-directory --directory=packages/hive-engine lint
	@$(MAKE) --no-print-directory --directory=services/hive-api lint


.PHONY: type-all
type-all:
	@$(MAKE) --no-print-directory --directory=packages/hive-agents type
	@$(MAKE) --no-print-directory --directory=packages/hive-engine type
	@$(MAKE) --no-print-directory --directory=services/hive-api type


.PHONY: check-all
check-all:
	@$(MAKE) --no-print-directory --directory=packages/hive-agents check
	@$(MAKE) --no-print-directory --directory=packages/hive-engine check
	@$(MAKE) --no-print-directory --directory=services/hive-api check
