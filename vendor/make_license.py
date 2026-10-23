"""
Vendor license tool — generate the signing keypair (once) and sign a license
for each customer company.

A license is an RSA-signed token (JWT, RS256) holding the company name, the
maximum number of employees, and an expiry date. Only the holder of the PRIVATE
key (you) can create a valid license; the app verifies it with the embedded
PUBLIC key, so a customer cannot forge or extend their own license.

Usage
-----
  # 1. Once, ever — create your signing keys:
  python make_license.py keygen
      -> writes license_private.pem  (KEEP SECRET, never ship)
      -> writes license_public.pem   (paste into backend/app/core/license.py)

  # 2. For each customer, sign a license:
  python make_license.py sign --company "Acme Pvt Ltd" --employees 20 --days 365
      -> prints the LICENSE KEY string. Put it in that customer's .env as
         LICENSE_KEY=...   (the installer can bake it in per customer).

Requires: cryptography, python-jose  (both already in the backend image — run
this inside the backend container if you don't have them on your machine:
  docker compose exec backend python /app/make_license.py sign --company ... )
"""
import argparse
import datetime
from pathlib import Path

PRIV = "license_private.pem"
PUB = "license_public.pem"


def keygen() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    Path(PRIV).write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    Path(PUB).write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    print(f"Wrote {PRIV}  (KEEP SECRET — this signs all licenses; never ship it)")
    print(f"Wrote {PUB}   (paste its contents into backend/app/core/license.py)")


def sign(company: str, employees: int, days: int, out: str | None) -> None:
    from jose import jwt

    priv = Path(PRIV).read_text()
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "iss": "attendance-system",
        "company": company,
        "max_employees": int(employees),
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(days=int(days))).timestamp()),
    }
    token = jwt.encode(claims, priv, algorithm="RS256")
    if out:
        Path(out).write_text(token)
        print(f"Wrote license to {out}")
    print(f"\nLicense for: {company}  |  max employees: {employees}  |  valid {days} days")
    print("Put this in the customer's .env as  LICENSE_KEY=<below>\n")
    print(token)


def main() -> None:
    p = argparse.ArgumentParser(description="Attendance System license tool")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="create the signing keypair (once)")
    s = sub.add_parser("sign", help="sign a license for a customer")
    s.add_argument("--company", required=True)
    s.add_argument("--employees", type=int, default=20)
    s.add_argument("--days", type=int, default=365)
    s.add_argument("--out", default=None)
    a = p.parse_args()
    if a.cmd == "keygen":
        keygen()
    elif a.cmd == "sign":
        sign(a.company, a.employees, a.days, a.out)


if __name__ == "__main__":
    main()
