import tempfile, unittest, csv
from pathlib import Path
from gep import catalog, workflow, release
FIELDS=['region_code','year','table_id','printed_page','pdf_page','source_file','metric','value','unit','status','notes']
def table(root, rows):
    p=root/'02_clean/statistics/yearbook_2024_selected.csv';p.parent.mkdir(parents=True)
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
        for row in rows:w.writerow(dict(region_code='110108',year='2024',table_id='5-5',printed_page='67',pdf_page='67',source_file='01_raw/statistics/book.pdf',metric=row.get('metric','水产品产量'),value=row.get('value',''),unit='吨',status=row.get('status','blank_unresolved'),notes=''))
    return p
class WorkbenchTests(unittest.TestCase):
    def test_blank_remains_pending_not_zero(self):
        with tempfile.TemporaryDirectory() as t:
            p=table(Path(t),[{}]);r=catalog.check(p)
            self.assertTrue(r['valid']);self.assertEqual(r['pending_count'],1)
            b=catalog.build(p);self.assertIsNone(b['pending'][0]['value']);self.assertEqual(len(b['observations']),0)
    def test_observed_nan_rejected(self):
        with tempfile.TemporaryDirectory() as t:self.assertFalse(catalog.check(table(Path(t),[{'value':'NaN','status':'observed'}]))['valid'])
    def test_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as t:self.assertFalse(catalog.check(table(Path(t),[{},{}]))['valid'])
    def test_example_pauses_and_estimate_needs_review(self):
        run=workflow.new_example();self.assertEqual(run['status'],'waiting_input')
        r=workflow.resolve(run,'fish',{'method':'area_yield','area_ha':12,'yield_t_ha':5,'evidence':'synthetic/example','operator':'analyst'})
        self.assertEqual(r['items']['fish']['status'],'pending_review');self.assertIsNone(r['gep_total']);self.assertEqual(r['items']['fish']['quantity_t'],60)
        a=workflow.approve(r,'fish','reviewer');self.assertEqual(a['items']['fish']['status'],'approved')
        self.assertNotEqual(a['run_id'],run['run_id']);self.assertEqual(run['items']['fish']['status'],'waiting_input')
    def test_invalid_fish_estimate_rejected(self):
        with self.assertRaises(ValueError):workflow.resolve(workflow.new_example(),'fish',{'method':'stock_survival','stock_count':100000,'survival':1.2,'weight_kg':.75,'harvest_fraction':1,'operator':'a','evidence':'synthetic'})
    def test_stock_fish_kg_to_t(self):
        r=workflow.resolve(workflow.new_example(),'fish',{'method':'stock_survival','stock_count':100000,'survival':.8,'weight_kg':.75,'harvest_fraction':1,'operator':'a','evidence':'synthetic'})
        self.assertEqual(r['items']['fish']['quantity_t'],60)
    def test_existing_run_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'run.json';workflow.save(workflow.new_example(),p)
            with self.assertRaises(FileExistsError):workflow.save(workflow.new_example(),p)
    def test_release_rejects_extra_unlisted_file(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'README.md').write_text('reference only');release.seal(d,'reference-test');self.assertTrue(release.verify(d)['valid'])
            (d/'unexpected.pdf').write_bytes(b'raw document');self.assertFalse(release.verify(d)['valid'])
    def test_release_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'README.md').write_text('reference only');release.seal(d,'reference-test');(d/'README.md').write_text('changed');self.assertFalse(release.verify(d)['valid'])
    def test_release_blocks_credential_files(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'.env').write_text('x=y')
            with self.assertRaises(ValueError):release.seal(d,'reference-test')
if __name__=='__main__':unittest.main()
