#!/usr/bin/env python3
"""Read-only Android LP metadata / extent reader.

Layout reference: AOSP system/core/fs_mgr/liblp/include/liblp/metadata_format.h
https://android.googlesource.com/platform/system/core/+/refs/heads/main/fs_mgr/liblp/include/liblp/metadata_format.h
No source files are opened for writing; only explicitly requested output is written.
"""
import argparse, hashlib, json, os, pathlib, re, struct, subprocess
import xml.etree.ElementTree as ET

def u(fmt,b,off=0): return struct.unpack_from('<'+fmt,b,off)
def name(b): return b.split(b'\0',1)[0].decode('ascii')

def elf_module_metadata(data):
    """Read ELF64 little-endian section metadata, without disassembly."""
    assert data[:6] == b'\x7fELF\x02\x01', 'expected ELF64 little endian'
    eh = u('HHIQQQIHHHHHH', data, 16)
    shoff, shsz, shnum, shstri = eh[5], eh[10], eh[11], eh[12]
    sh = [u('IIQQQQIIQQ', data, shoff + i * shsz) for i in range(shnum)]
    strtab = data[sh[shstri][4]:sh[shstri][4] + sh[shstri][5]]
    sections = {strtab[v[0]:].split(b'\0', 1)[0].decode(): v for v in sh}
    v = sections['.modinfo']
    modinfo = [x.decode(errors='replace') for x in data[v[4]:v[4]+v[5]].split(b'\0') if x]
    return dict(elf_type=eh[0], machine=eh[1], modinfo=modinfo,
                has___versions='__versions' in sections,
                imported_symbols_note='__versions records CRCs of imported kernel symbols; no code analysis performed')

class Erofs:
    """Read selected files through dump.erofs, never unpack a whole partition.

    For fragmented partitions, paths are accepted only if all inode metadata,
    intermediate directory extents, and file data fit inside the first linear
    LP extent. This is sufficient for the selected evidence in this package.
    Other files are rejected rather than read using an incorrect linear map.
    """
    def __init__(self, super_image, tool):
        self.super = super_image
        self.tool = str(pathlib.Path(tool).resolve())
        self.env = os.environ.copy()
        # Isolated Homebrew bottle's lz4/xz dependencies, if using it on macOS.
        libs = ['/opt/homebrew/opt/lz4/lib', '/opt/homebrew/opt/xz/lib']
        previous = self.env.get('DYLD_LIBRARY_PATH')
        self.env['DYLD_LIBRARY_PATH'] = ':'.join(libs + ([previous] if previous else []))
        self.validated = set()

    def run(self, pn, path, operation):
        first = self.super.partitions[pn]['extents'][0]
        assert first['target_type'] == first['target_source'] == 0
        cmd = [self.tool, '--offset=' + str(first['target_data'] * 512),
               '--path=' + path, operation, self.super.path]
        return subprocess.check_output(cmd, env=self.env, stderr=subprocess.PIPE)

    def validate_path(self, pn, path):
        first = self.super.partitions[pn]['extents'][0]
        limit = first['num_sectors'] * 512
        sb = self.super.part_read(pn, 1024, 128)
        blksz = 1 << sb[12]
        meta = u('I', sb, 40)[0] * blksz
        components = pathlib.PurePosixPath(path).parts
        prefixes = ['/'] + ['/' + '/'.join(components[1:i]) for i in range(2, len(components)+1)]
        for prefix in prefixes:
            if (pn, prefix) in self.validated:
                continue
            details = self.run(pn, prefix, '-e').decode()
            nid = int(re.search(r'^NID:\s+(\d+)', details, re.M)[1])
            inode_size = int(re.search(r'^Inode size:\s+(\d+)', details, re.M)[1])
            xattr_size = int(re.search(r'Xattr size:\s+(\d+)', details)[1])
            assert meta + nid * 32 + inode_size + xattr_size <= limit, (pn, prefix, 'metadata spans LP extents')
            ends = [int(v) for v in re.findall(r':\s+\d+\.\.\s*(\d+)\s*\|', details)]
            assert not ends or max(ends) <= limit, (pn, prefix, 'data spans LP extents')
            self.validated.add((pn, prefix))

    def cat(self, pn, path):
        self.validate_path(pn, path)
        return self.run(pn, path, '--cat')

    def ls(self, pn, path):
        self.validate_path(pn, path)
        return self.run(pn, path, '--ls').decode()

def collect_evidence(s, tool, outdir):
    outdir = pathlib.Path(outdir)
    erofs = Erofs(s, tool)
    files, counts = [], {}
    for pn in ('system_dlkm_a', 'vendor_dlkm_a'):
        listing = erofs.ls(pn, '/lib/modules')
        (outdir / (pn+'-lib_modules.txt')).write_text(listing)
        names = re.findall(r'^\s+\d+\s+1\s+(\S+\.ko)$', listing, re.M)
        counts[pn] = dict(ko_count=len(names), module_directory='/lib/modules',
                          layout='flat; no kernel-version subdirectory')
    selected = [
        ('system_dlkm_a', '/lib/modules/6lowpan.ko'),
        ('vendor_dlkm_a', '/lib/modules/lenovo_thermal_control.ko'),
        ('vendor_dlkm_a', '/lib/modules/msm_kgsl.ko'),
        ('vendor_dlkm_a', '/lib/modules/msm_drm.ko'),
        ('vendor_dlkm_a', '/lib/modules/goodix_ts.ko'),
        ('vendor_dlkm_a', '/lib/modules/modules.load'),
        ('vendor_dlkm_a', '/lib/modules/modules.dep'),
        ('system_dlkm_a', '/lib/modules/modules.load'),
        ('vendor_a', '/build.prop'), ('odm_a', '/build.prop'),
        ('vendor_a', '/etc/vintf/compatibility_matrix.xml'),
        ('vendor_a', '/etc/vintf/manifest_elden_prc_wifi.xml'),
        ('system_a', '/system/build.prop'),
        ('system_a', '/system/etc/vintf/compatibility_matrix.202404.xml'),
        ('system_a', '/system/etc/vintf/compatibility_matrix.202504.xml'),
        ('system_a', '/system/etc/vintf/compatibility_matrix.device.xml'),
        ('system_a', '/system/etc/vintf/manifest.xml'),
        ('vendor_dlkm_a', '/etc/build.prop'),
        ('system_dlkm_a', '/etc/build.prop'),
    ]
    vintf, properties = {}, {}
    for pn, src in selected:
        data = erofs.cat(pn, src)
        dst = outdir / 'files' / pn / src.lstrip('/')
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        entry = dict(partition=pn, source_path=src, output=str(dst.resolve()),
                     size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                     within_first_extent=True)
        if src.endswith('.ko'):
            entry.update(elf_module_metadata(data))
        if src.endswith('.xml'):
            root = ET.fromstring(data)
            vintf[pn+':'+src] = dict(root=root.tag, attributes=root.attrib,
                kernel_entries=sorted({tuple(sorted(el.attrib.items())) for el in root.findall('kernel')}))
        if src.endswith('build.prop'):
            properties[pn+':'+src] = dict(line.split('=',1) for line in data.decode().splitlines()
                if '=' in line and not line.lstrip().startswith('#'))
        files.append(entry)
    (outdir/'selected-files.json').write_text(json.dumps(files, indent=2)+'\n')
    summary = dict(module_directories=counts, vintf=vintf, properties=properties,
                   source_mutation=False, erofs_tool=str(pathlib.Path(tool).resolve()),
                   limitation='Selected files only. Fragmented LP reads rejected unless all needed extents fit inside the first linear extent. No full filesystem validation or device boot test.')
    (outdir/'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(dict(module_directories=counts, selected_files=len(files),
                         selected_bytes=sum(e['size'] for e in files)), ensure_ascii=False))

class Super:
    def __init__(self,path,slot=0):
        self.path=str(path); self.f=open(path,'rb'); self.bytes_read=0
        g=self.read(4096,52); magic,sz=u('II',g)
        assert magic==0x616c4467 and sz==52
        assert hashlib.sha256(g[:8]+bytes(32)+g[40:]).digest()==g[8:40]
        maxsz,slots,logical=u('III',g,40); assert slot<slots
        base=12288+maxsz*slot; hdr=self.read(base,128)
        magic,major,minor,hsz=u('IHHI',hdr); assert magic==0x414c5030
        if hsz>128: hdr=self.read(base,hsz)
        assert hashlib.sha256(hdr[:12]+bytes(32)+hdr[44:]).digest()==hdr[12:44]
        tsz=u('I',hdr,44)[0]; t=self.read(base+hsz,tsz)
        assert hashlib.sha256(t).digest()==hdr[48:80]
        desc=[u('III',hdr,80+12*i) for i in range(4)]
        tables=[]
        for start,n,size in desc: tables.append([t[start+i*size:start+(i+1)*size] for i in range(n)])
        self.extents=[dict(zip(('num_sectors','target_type','target_data','target_source'),u('QIQI',e))) for e in tables[1]]
        self.partitions={}
        for p in tables[0]:
            attrs,first,n,group=u('IIII',p,36)
            exts=self.extents[first:first+n]
            self.partitions[name(p[:36])]=dict(attributes=attrs,first_extent_index=first,num_extents=n,group_index=group,extents=exts,size=sum(e['num_sectors']*512 for e in exts))
        self.metadata=dict(image=self.path,image_size=os.path.getsize(path),geometry=dict(metadata_max_size=maxsz,metadata_slot_count=slots,logical_block_size=logical,checksum_valid=True),header=dict(version=f'{major}.{minor}',size=hsz,tables_size=tsz,header_checksum_valid=True,tables_checksum_valid=True),groups=[dict(name=name(p[:36]),flags=u('I',p,36)[0],maximum_size=u('Q',p,40)[0]) for p in tables[2]],block_devices=[dict(first_logical_sector=u('Q',p)[0],alignment=u('I',p,8)[0],alignment_offset=u('I',p,12)[0],size=u('Q',p,16)[0],partition_name=name(p[24:60]),flags=u('I',p,60)[0]) for p in tables[3]],partitions=self.partitions)
    def read(self,off,n):
        self.f.seek(off); b=self.f.read(n); self.bytes_read+=len(b); assert len(b)==n; return b
    def part_read(self,part,off,n):
        p=self.partitions[part]; assert 0<=off<=p['size'] and off+n<=p['size']
        out=[]; cursor=0
        for e in p['extents']:
            esz=e['num_sectors']*512
            if off<cursor+esz and n:
                rel=max(off-cursor,0); count=min(esz-rel,n)
                assert e['target_source']==0
                out.append(bytes(count) if e['target_type']==1 else self.read(e['target_data']*512+rel,count))
                off+=count; n-=count
            cursor+=esz
        assert n==0; return b''.join(out)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image');ap.add_argument('--json')
    ap.add_argument('--output-dir', default='.work/super-inspection')
    ap.add_argument('--collect', action='store_true', help='Read this package\'s selected module/property/VINTF evidence')
    ap.add_argument('--erofs-tool', default='.work/super-inspection/erofs-utils/1.9.4/bin/dump.erofs')
    args=ap.parse_args()
    outdir=pathlib.Path(args.output_dir);outdir.mkdir(parents=True,exist_ok=True)
    s=Super(args.image)
    for pn,p in s.partitions.items():
        sig=s.part_read(pn,0,min(4096,p['size'])) if p['size'] else b''
        p['filesystem']='erofs' if sig[1024:1028]==b'\xe2\xe1\xf5\xe0' else 'ext4' if sig[1080:1082]==b'\x53\xef' else 'unknown'
        print(pn,p['size'],p['filesystem'],json.dumps(p['extents']))
    pathlib.Path(args.json or outdir/'lp-metadata.json').write_text(json.dumps(s.metadata,indent=2)+'\n')
    if args.collect: collect_evidence(s, args.erofs_tool, outdir)
    print('LP reader bytes read (excludes dump.erofs reads):',s.bytes_read)
if __name__=='__main__': main()
