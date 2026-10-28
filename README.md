<<<<<<< HEAD
# RP2-Project
=======
# Power BI Dashboard Testing Agent

## Run the app

From the project folder:

```powershell
streamlit run src/main.py
```

## Run tests

```powershell
python -m unittest discover -v
```

## Project layout

```text
src/
  main.py                       Streamlit app
  core/                         Shared configuration and findings
  github_scanner/               GitHub repository scanning
  data_analysis/                CSV quality and SQL validation
  powerbi/                      DAX, model, project, and ticket validation
  ai/                           AI recommendations
  reports/                      HTML report generation
tests/                          Automated tests
requirements.txt        Python dependencies
.env                    Local configuration and secrets
```
>>>>>>> aeae3c3 (Clean up project architecture)
