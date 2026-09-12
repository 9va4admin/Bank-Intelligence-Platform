"""Update dev account passwords to Astra@1212 and reset TOTP enrollment.

Revision ID: 20260912_dev_pwd_reset
Revises: 20260719_p_secviol
Create Date: 2026-09-12

All dev seed accounts migrated from bank-specific passwords (astra-dev-ops, etc.)
to the unified demo password Astra@1212. TOTP enrollment reset so every user
scans QR fresh on next login.
"""
from __future__ import annotations

from alembic import op

revision = "20260912_dev_pwd_reset"
down_revision = "20260719_p_secviol"
branch_labels = None
depends_on = None

# argon2id hashes for "Astra@1212" — one unique salt per account
_HASHES = {
    # (username, bank_id): hash
    ("__astra-admin", "saraswat-coop"):
        "$argon2id$v=19$m=65536,t=3,p=4$CPb2L30JvtY10y47EtfiHQ$JEXeQqLDQ1o6DNQmU4sU7NLCP0ugUXNmsV/BJt5DwPg",
    ("__astra-admin", "federal-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$Gj2yu3h1rHzNFigxvh6BBw$W+MJ1ytezyMH4nHiYUoFp7A/a9UIxmIfS6OfxmeMzdg",
    ("admin",         "saraswat-coop"):
        "$argon2id$v=19$m=65536,t=3,p=4$Lmz2E3Dkfg64gFm690RdPQ$sUemvdc0eOmZnMNSTkkWhudwrhwyqf2gKAaSS0pUT+c",
    ("ops",           "saraswat-coop"):
        "$argon2id$v=19$m=65536,t=3,p=4$zZimm1cAWIY2dSzsvgNiGw$zrfcxNhmMtjEolZLnpXt1V8oB8yHaLM7CSorAjH9sMc",
    ("smb",           "smb-mh-vasavi"):
        "$argon2id$v=19$m=65536,t=3,p=4$eGFdQgcAHS2gaTEMQYBjrg$cjyMi1RHUMN9znIrTd8eAZTiAja7offwdmXravd5B7I",
    ("fed-admin",     "federal-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$0ellp7roCvUcQLHdKdUZkg$CVW5VULo2q+pCFGJ32C9Yahk22kMjjAVr0/ctdvlC7k",
    ("fed-ops",       "federal-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$Wi+OUJfDvDBfacPSKzUnSg$Ba/CsrEFqBswimccXiWqRPZyN0eXcZw8Tap/U50oU18",
    ("fed-reviewer",  "federal-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$QDcGjMn5uY0oE2+gUTM9Bg$A/dh4vL7SObBSE5MOk3EzRepu7MtN+Ajk+JTtZZksqk",
    ("ubi-admin",     "union-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$O2CWeM8WOr95Nnd6/MP8aA$WwWmVoQeTo2XigNksW3eA1zaMO+bgfJLimbAmUfjEzQ",
    ("ubi-ops",       "union-bank"):
        "$argon2id$v=19$m=65536,t=3,p=4$jFVZshhgvU9u6yv7dpmQvg$ZhTjozI7U0tfMdaE0QsJn4Mz7Ic5UpDJ4bE+hq2CjrU",
    ("ubi-smb",       "smb-mh-nmcb"):
        "$argon2id$v=19$m=65536,t=3,p=4$QjZ2qJJw9bWgVHzS3/i5Bw$DSIePFohMZD2mzMZ/jz4C9Sx6kGl4rdUhPju9OByZyk",
}


def upgrade() -> None:
    conn = op.get_bind()
    for (username, bank_id), pwd_hash in _HASHES.items():
        conn.execute(
            "UPDATE platform.local_auth_accounts "
            "SET password_hash = %s, totp_enrolled = false, "
            "    failed_attempts = 0, locked_until = NULL "
            "WHERE username = %s AND bank_id = %s",
            (pwd_hash, username, bank_id),
        )


def downgrade() -> None:
    # Passwords are one-way hashed; downgrade cannot restore original values.
    pass
