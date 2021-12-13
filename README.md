Brief instructions. Customize as you please:

```bash
apt install openmodelica # See instructions on https://openmodelica.org
omc .CI/installLibraries.mos # Or install the libraries you need to test yourself
pip install -r requirements.txt
./test.py --noclean configs/conf.json # sqlite3.db is then generated
./report.py configs/conf.json
# Upload the relevant files somewhere. Backup sqlite3.db
```

There are flags such as --branch to test.py in order to test different OMC versions.
