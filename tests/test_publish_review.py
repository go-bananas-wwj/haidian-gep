import io, json, tempfile, unittest, types, sys
from pathlib import Path
from unittest.mock import patch
from gep import release, workflow, fetch

class ReviewTests(unittest.TestCase):
    def test_manifest_rejects_scope_and_path(self):
        for key,value in [('scope','full_gep'),('release_id','../outside')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as t:
                d=Path(t);(d/'README.md').write_text('ref');release.seal(d,'reference-test')
                p=d/'manifest.json';m=json.loads(p.read_text());m[key]=value;p.write_text(json.dumps(m))
                self.assertFalse(release.verify(d)['valid'])
    def test_new_proposal_clears_previous_review(self):
        p={'method':'manual','quantity_t':60,'operator':'a','evidence':'synthetic'}
        a=workflow.approve(workflow.resolve(workflow.new_example(),'fish',p),'fish','b')
        r=workflow.resolve(a,'fish',{**p,'quantity_t':65})
        self.assertNotIn('reviewer',r['items']['fish']);self.assertEqual(a['items']['fish']['reviewer'],'b')
    def test_upload_uses_closed_snapshot_and_preserves_commit(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'README.md').write_text('ref');release.seal(d,'reference-test')
            sent={};case=self
            class API:
                def __init__(self,**kw):pass
                def list_repo_files(self,*a,**kw):
                    (d/'unexpected.txt').write_text('new local content')
                    return [types.SimpleNamespace(path='releases/reference-test/'+n,type='blob') for n in sent]
                def upload_folder(self,repo,typ,folder,**kw):
                    case.assertNotEqual(Path(folder),d)
                    case.assertEqual(set(kw['allow_patterns']),{'README.md','manifest.json'})
                    case.assertFalse(kw['use_cache'])
                    for p in Path(folder).rglob('*'):
                        if p.is_file():sent[p.relative_to(folder).as_posix()]=p.read_bytes()
                    return {'CommitId':'abc123','CommitMessage':'test'}
                def download_file(self,repo,typ,path,**kw):
                    p=Path(kw['local_dir'])/Path(path).name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(sent[Path(path).name]);return p
            with patch.dict(sys.modules,{'modelscope_hub':types.SimpleNamespace(HubApi=API)}):
                result=release.upload(d,'example/data','test-placeholder')
            self.assertEqual(set(sent),{'README.md','manifest.json'})
            self.assertEqual(result['commit_ids'],['abc123'])
    def test_public_download_sets_user_agent(self):
        with tempfile.TemporaryDirectory() as t:
            def response(req,**kw):
                self.assertIsInstance(req,fetch.urllib.request.Request)
                self.assertTrue(req.get_header('User-agent').startswith('haidian-gep'))
                return io.BytesIO(b'public reference')
            with patch('gep.fetch.urllib.request.urlopen',side_effect=response):
                r=fetch.download('aef-readme',t)
            self.assertEqual(r['bytes'],16)
