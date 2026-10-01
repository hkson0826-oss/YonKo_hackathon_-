"""Bounded single GCC12 context for final exact-ZIP checks; only /tmp outputs."""
from pathlib import Path
import json, os, shlex, signal, sys, time
sys.dont_write_bytecode=True
ROOT=Path('/tmp/yk-new-bot-20261001'); OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'experiments'))
from verify_gcc12_tmp import gcc12_toolchain,run,sha
sys.path.insert(0,str(ROOT/'yk-development-tools/bots/dist/starter'))
from submission import inspect_zip,extract_zip
report={'status':'preparing','script_sha256':sha(Path(__file__))}
def write(name,obj):
 p=OUT/name; tmp=p.with_suffix(p.suffix+'.partial');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def stop(*args):raise KeyboardInterrupt('Stopped')
for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,stop)
try:
 with gcc12_toolchain(report,budget_seconds=1900) as tc:
  report['status']='ready';report['wrapper']=tc['compiler_wrapper'];write('toolchain.json',report)
  done=set()
  while time.time()<1790833680: # 2026-10-01 14:48 KST; stop well before submission deadline
   if (OUT/'STOP').exists():break
   for request in sorted(OUT.glob('request-*.json')):
    if request.name in done:continue
    done.add(request.name);r=json.loads(request.read_text());name=request.stem.removeprefix('request-');z=Path(r['zip']).resolve()
    result={'status':'started','zip':str(z),'zip_sha256':sha(z),'scope':'Exact ZIP GCC12.2 C++20/O2 build and official SDK smoke; not strength or CPU-quota validation.'}
    try:
     if 'sha256'in r and sha(z)!=r['sha256']:raise ValueError('Requested ZIP hash mismatch')
     result['inspection']=inspect_zip(z)
     if not result['inspection']['ok']:raise ValueError('ZIP inspection failed')
     src=tc['work']/('source-'+name);src.mkdir();assert extract_zip(z,src)=='cpp'
     result['source_sha256']={str(p.relative_to(src)):sha(p) for p in sorted(src.rglob('*'))if p.is_file()}
     binary=tc['work']/('bot-'+name)
     result['build']=run([tc['compiler_wrapper'],'-std=c++20','-O2','-I',str(src),*[str(p)for p in sorted(src.rglob('*.cpp'))],'-o',str(binary)],env=tc['env'],cwd=tc['work'],deadline=tc['deadline'])
     assert result['build']['returncode']==0,'GCC12 compile failed'
     result['binary_sha256']=sha(binary);result['binary']=str(binary)
     result['elf']=run(['readelf','-l',str(binary)],env=tc['env'],cwd=tc['work'],deadline=tc['deadline'])
     assert str(tc['sysroot']/'lib/x86_64-linux-gnu/ld-linux-x86-64.so.2')in result['elf']['stdout']
     result['sdk']=run([sys.executable,str(ROOT/'yk-development-tools/bots/dist/starter/run_tests.py'),'--bot',str(binary),'--seed',str(r.get('seed',23599))],env=tc['env'],cwd=tc['work'],deadline=tc['deadline'])
     result['sdk_result']=json.loads(result['sdk']['stdout']);assert result['sdk']['returncode']==0 and result['sdk_result']['ok']
     assert sha(z)==result['zip_sha256'],'ZIP changed during verification'
     result['status']='passed'
    except Exception as e:result.update(status='failed',error=repr(e))
    write('result-'+name+'.json',result)
   time.sleep(0.2)
  report['status']='closed'
except (Exception,KeyboardInterrupt) as e:report.update(status='failed',error=repr(e))
finally:write('toolchain.json',report)
