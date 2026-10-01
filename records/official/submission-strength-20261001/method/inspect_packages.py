import importlib
import importlib.util
import importlib.metadata
import json
import sys
names=['numpy','scipy','pandas','statsmodels','sklearn','pymc','arviz','matplotlib','networkx']
result={'python':sys.version,'executable':sys.executable,'packages':{}}
for name in names:
 available=bool(importlib.util.find_spec(name));row={'module_found':available}
 if available:
  try:
   module=importlib.import_module(name);row.update(import_ok=True,version=getattr(module,'__version__',None))
  except Exception as error:row.update(import_ok=False,error=repr(error))
 result['packages'][name]=row
print(json.dumps(result,indent=2))
