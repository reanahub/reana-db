# Changelog

## [0.9.4](https://github.com/reanahub/reana-db/compare/0.9.3...0.9.4) (2024-03-01)


### Code refactoring

* **docs:** move from reST to Markdown ([#225](https://github.com/reanahub/reana-db/issues/225)) ([b48eb55](https://github.com/reanahub/reana-db/commit/b48eb55f7a1b1bbdde0e0a458852349a439a511e))


### Code style

* **black:** format with black v24 ([#224](https://github.com/reanahub/reana-db/issues/224)) ([cc60522](https://github.com/reanahub/reana-db/commit/cc6052242fd14cf3413b793d0aa32a24871fe1b1))


### Continuous integration

* **commitlint:** addition of commit message linter ([#218](https://github.com/reanahub/reana-db/issues/218)) ([ee0f7e5](https://github.com/reanahub/reana-db/commit/ee0f7e5e106e0be619779bfa2133415feecc323b))
* **commitlint:** allow release commit style ([#229](https://github.com/reanahub/reana-db/issues/229)) ([adf15d7](https://github.com/reanahub/reana-db/commit/adf15d7c6457eddadc3da1aa8b95b74cfc1239fb))
* **commitlint:** check for the presence of concrete PR number ([#223](https://github.com/reanahub/reana-db/issues/223)) ([3d513f6](https://github.com/reanahub/reana-db/commit/3d513f6cda44e9e40b3c8f3967fcb87d113287ec))
* **pytest:** move to PostgreSQL 14.10 ([#226](https://github.com/reanahub/reana-db/issues/226)) ([4dac889](https://github.com/reanahub/reana-db/commit/4dac88953754c0810d3502e8e511ec90c27c2b43))
* **release-please:** initial configuration ([#218](https://github.com/reanahub/reana-db/issues/218)) ([7c616d6](https://github.com/reanahub/reana-db/commit/7c616d67fac642656f56d37422ba69c4a8d4fa20))
* **shellcheck:** fix exit code propagation ([#223](https://github.com/reanahub/reana-db/issues/223)) ([b62ee1e](https://github.com/reanahub/reana-db/commit/b62ee1e3be44628265bf5ada7e0b7eb88e283c00))


### Documentation

* **authors:** complete list of contributors ([#227](https://github.com/reanahub/reana-db/issues/227)) ([3fbcf65](https://github.com/reanahub/reana-db/commit/3fbcf65db735146d54078cae4c5b9c8968ead055))

## 0.9.3 (2023-12-01)

- Changes the `Workflow` table to replace the `run_number` column with two new columns `run_number_major` and `run_number_minor` in order to allow for more than nine restarts of user workflows.
- Changes the names of database table, column, index and key constraints in order to follow the SQLAlchemy upstream naming conventions everywhere.
- Changes several database index definitions in order to improve performance of most common database queries.

## 0.9.2 (2023-09-26)

- Adds progress meter to the logs of the periodic quota updater.
- Changes CPU and disk quota calculations to improve the performance of periodic quota updater.
- Fixes the workflow priority calculation to avoid workflows stuck in the `queued` status when the number of allowed concurrent workflow is set to zero.

## 0.9.1 (2023-01-18)

- Changes to PostgreSQL 12.13.
- Fixes conversion of possibly-negative resource usage values to human-readable formats.
- Fixes disk quota updater to prevent setting negative disk quota usage values.
- Fixes quota updater to reduce memory usage.

## 0.9.0 (2022-12-13)

- Adds new `launcher_url` column to the `Workflow` table to store the remote origin of workflows submitted via the Launch-on-REANA functionality.
- Adds the possibility to force resource quota updates irrespective of globally-configured quota update policy.
- Adds new `WorkspaceRetentionRule` table to store workspace file retention rules.
- Adds new `WorkspaceRetentionAuditLog` table to store the audit log of workspace file retention rule updates.
- Changes percentage ranges used to calculate the health status of user resource quota usage.
- Changes to PostgreSQL 12.10.
- Fixes wrong numbering of restarted workflows by limiting the number of times a workflow can be restarted to nine.
- Fixes `Workflow.get_workspace_disk_usage` to always calculate disk usage rather than relying on the quota usage values from the database, since these may not be up-to-date depending on the global quota update policy.
- Fixes helper function that retrieves workflows by UUID to also additionally check that the provided user is the owner of the workflow.

## 0.8.2 (2022-02-23)

- Adds transition for workflow from queued to failed status.

## 0.8.1 (2022-02-01)

- Adds an option to periodically calculate CPU quota usage.
- Changes CLI quota command from `disk-usage-update` to `resource-usage-update` since it can also perform CPU quota calculation.
- Fixes quota update functions to handle exceptional situation as continuable errors.
- Removes extra `QuotaResourceType` enum in favor of `ResourceType.name`.

## 0.8.0 (2021-11-22)

- Adds new disk usage retrieval methods using canonical (bytes) and human-readable (KiB) units. (`User`, `Workflow`)
- Adds Quota models which calculates CPU and disk usage.
- Adds `InteractiveSession` model.
- Adds new properties `started_at` and `finished_at` to the `Job` model, updated on status change.
- Adds `get_priority` workflow method, that combines both complexity and concurrency, to pass to the scheduler.
- Adds a possibility to configure database connection pool parameters via environment variables.
- Adds new `pending` state to `RunStatus` table.
- Adds workflow complexity property in `Workflow` table.
- Adds environment variable to configure which quotas to update.
- Changes `WorkflowStatus` table to `RunStatus`.
- Changes disk quota calculation functions to allow passing raw bytes to increase the used quota.
- Changes to PostgreSQL 12.8.
- Removes support for Python 2.

## 0.7.3 (2021-03-17)

- Fixes REANA installation by pinning SQLAlchemy version less than 1.4.0 due to <https://github.com/kvesteri/sqlalchemy-utils/issues/505>.

## 0.7.2 (2021-02-22)

- Adds utility to status enums to decide whether to clean workflows and jobs depending on their status.

## 0.7.1 (2021-02-02)

- Adds support for Python 3.9.
- Fixes minor code warnings.
- Changes CI system to include Python flake8 checker.

## 0.7.0 (2020-10-20)

- Adds initial central workflow status transition logic handler.
- Adds new audit table and logic to register actions. (`AuditLog`, `AuditLogAction`)
- Adds fixtures for better testing of database models.
- Changes user token storage to move tokens from `User` table to `UserToken` table and to encrypt them.
- Changes `Workflow` table to add a new `workspace_path` column.
- Changes default database service to use centrally configured one from REANA-Commons. (`REANA_INFRASTRUCTURE_COMPONENTS_HOSTNAMES`)
- Changes code formatting to respect `black` coding style.
- Changes documentation to single-page layout.

## 0.6.0 (2019-12-19)

- Adds new method which returns full workflow name.
- Adds more granular DB configuration.
- Adds Git repository information to the workflow model.
  (`Workflow.git_repo`, `Workflow.git_provider`)
- Adds user name information to the user model.
  (`User.full_name`, `User.username`)
- Removes restart count information from the job model.
  (`Job.restart_count`, `Job.max_restart_count`)
- Adds support for Python 3.8.

## 0.5.0 (2019-04-16)

- Introduces new workflow statuses: `deleted`, `stopped`, `queued`.
- Adds new field to store workflow stopping time. (`Workflow.run_stopped_at`)
- Moves workflow input parameters to its own column to separate them from
  operational options. Adapts getters accordingly.
  (`Workflow.input_parameters`)
- Adds new method to retrieve the workflow owner's token.
  (`Workflow.get_owner_access_token`)
- Introduces new utility function to retrieve workflows by `uuid` or name.
  (`_get_workflow_with_uuid_or_name`)
- Introduces new fields for interactive sessions: `interactive_session`,
  `interactive_session_name` and `interactive_session_type`. Note that with
  current design only one interactive session per workflow is supported.
- Adds a new enumeration for possible job statuses. (`JobStatus`)
- Adds new field to identify jobs in the underlying compute backend.
  (`Job.backend_job_id`)

## 0.4.0 (2018-11-06)

- Stores `reana.yaml` in database models.
- Adds Workflow specification and parameter getters.
- Adds support for Python 3.7.
- Changes license to MIT.

## 0.3.0 (2018-08-10)

- This package is a result of refactoring [reana-commons](https://reana-commons.readthedocs.io/).
- Provides common REANA models.
- Provides database connection logic.
