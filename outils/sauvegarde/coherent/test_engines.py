import json
from pathlib import Path
import engines


def test_postgres_exports_each_database_and_roles(tmp_path):
    class Fake:
        def inspect(self): return [{'Name':'/pg','Config':{'Env':['POSTGRES_USER=owner']}}]
        def run(self,args,output=None):
            if output:
                output.write_bytes(b'native backup'); return b''
            sql=args[-1]
            if 'rolsuper' in sql:return b't'
            if 'pg_database' in sql: return b'["postgres","app"]'
            if 'server_version' in sql: return b'16.14'
            if 'pg_extension' in sql: return b'[{"name":"vector","version":"0.8.2"}]'
            if 'pg_tables' in sql: return json.dumps([{'schema':'public','name':'odd"table'}]).encode()
            return b'38'
    target=tmp_path/'pg'
    engines.postgres(Fake(),{'container':'pg','image':'pg16','restore_image':'pg16'},target)
    m=json.loads((target/'meta.json').read_text())
    assert [d['name'] for d in m['databases']]==['postgres','app']
    assert m['databases'][1]['table_counts']=={'"public"."odd""table"':38}
    assert (target/'roles.sql').read_bytes()==b'native backup'
    assert (target/'meta.json').stat().st_mode & 0o777 == 0o600

def test_postgres_prefers_patroni_superuser_for_roles(tmp_path):
    class Fake:
        def __init__(self):self.users=[]
        def inspect(self):return [{'Name':'/pg','Config':{'Env':['POSTGRES_USER=application','PATRONI_SUPERUSER_USERNAME=administrator']}}]
        def run(self,args,output=None):
            self.users.append(args[args.index('-U')+1])
            if output:output.write_bytes(b'export');return b''
            if 'rolsuper' in args[-1]:return b't'
            if 'pg_database' in args[-1]:return b'[]'
            return b'16.14'
    fake=Fake();engines.postgres(fake,{'container':'pg','image':'pg16'},tmp_path/'pg')
    assert fake.users and set(fake.users)=={'administrator'}

def test_postgres_rejects_non_superuser_before_roles_export(tmp_path):
    import pytest
    class Fake:
        def inspect(self):return [{'Name':'/pg','Config':{'Env':['POSTGRES_USER=limited']}}]
        def run(self,args,output=None):
            assert output is None,'no sensitive roles export with limited user'
            return b'f' if 'rolsuper' in args[-1] else b'[]'
    with pytest.raises(Exception,match='superuser'):engines.postgres(Fake(),{'container':'pg','image':'pg16'},tmp_path/'pg')

def test_etcd_cleanup_uses_helper_on_exact_volume_without_source_rm(tmp_path):
    class Fake:
        def __init__(self):self.calls=[]
        def inspect(self):return [{'Name':'/etcd','Mounts':[{'Type':'volume','Name':'etcd_data','Destination':'/var/etcd'}]}]
        def run(self,args,**kwargs):
            self.calls.append(args)
            if args[0]=='cp':Path(args[2]).write_bytes(b'snapshot')
            if args[:3]==['exec','etcd','rm']:raise AssertionError('minimal image has no rm')
            return b'{}'
    fake=Fake();engines.etcd(fake,{'container':'etcd','image':'etcd35'},tmp_path/'etcd')
    cleanup=fake.calls[-1]
    assert cleanup[0]=='run';assert '--entrypoint' in cleanup
    assert 'type=volume,src=etcd_data,dst=/cleanup' in cleanup
    assert 'unlink' in cleanup[-2]
