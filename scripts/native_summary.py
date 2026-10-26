from pathlib import Path
import json
import xml.etree.ElementTree as E
root=Path(__file__).resolve().parents[1]/"android/app/build"
suites=[E.parse(p).getroot() for p in (root/"test-results/testDebugUnitTest").glob("TEST-*.xml")]
issues=E.parse(root/"reports/lint-results-debug.xml").getroot()
summary={"tests":{k:sum(int(s.get(k,"0")) for s in suites) for k in ["tests","failures","errors","skipped"]},"lint":{k:sum(i.get("severity")==k for i in issues) for k in ["Error","Fatal","Warning","Information"]}}
print(json.dumps(summary,indent=2))
