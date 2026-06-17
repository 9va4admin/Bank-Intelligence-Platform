# /new-bank

Scaffold configuration for onboarding a new bank to ASTRA.

## Usage
/new-bank [bank_id] [bank_name] [cbs_type] [modules]

## Example
/new-bank kotak-mah "Kotak Mahindra Bank" finacle cts,ej

## What This Does
1. Creates `infra/helm/values/banks/{bank_id}.yaml` from bank-template.yaml
2. Sets `bank_id`, `bank_name`, `cbs_connector_type`
3. Enables/disables modules per request
4. Generates a `BankOnboardingWorkflow` trigger config
5. Lists manual steps remaining (IdP SAML config, HSM key ceremony, CBS connector test)

## Output
- New Helm values file for the bank
- Checklist of manual onboarding steps
- Estimated time: 2-4 hours for a standard bank onboarding
