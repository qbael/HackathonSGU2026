from pathlib import Path
from xml.etree import ElementTree as E
import re, json, html, textwrap
ROOT=Path(__file__).resolve().parents[3]
CACHE=ROOT/'.cache/docs/erd'
CACHE.mkdir(parents=True,exist_ok=True)
SQL=(ROOT/'docs/database/database-schema.sql').read_text()
OUT=ROOT/'docs/database/findie-erd.drawio'

def split_top(s):
    out=[]; level=0; quoted=False; start=0
    for i,c in enumerate(s):
        if c=="'": quoted=not quoted
        if not quoted:
            if c=='(': level+=1
            elif c==')': level-=1
            elif c==',' and level==0: out.append(s[start:i].strip()); start=i+1
    out.append(s[start:].strip())
    return out

def table_body(start):
    depth=1; quoted=False
    for i in range(start,len(SQL)):
        c=SQL[i]
        if c=="'": quoted=not quoted
        if not quoted:
            if c=='(': depth+=1
            elif c==')':
                depth-=1
                if depth==0: return SQL[start:i]
    raise AssertionError('unclosed table')

catalog={}
for m in re.finditer(r'CREATE TABLE (\w+) \(',SQL):
    name=m[1]; cols=[]; pks=[]; uqs=[]; fks=[]
    for definition in split_top(table_body(m.end())):
        if definition.startswith('PRIMARY KEY'):
            pks=re.search(r'\((.*?)\)',definition)[1].split(', ')
        elif definition.startswith('UNIQUE'):
            uqs.append({'cols':re.search(r'\((.*?)\)',definition)[1].split(', '),'where':None})
        elif definition.startswith('FOREIGN KEY'):
            f=re.search(r'FOREIGN KEY \((.*?)\) REFERENCES (\w+)\((.*?)\)',definition)
            fks.append({'cols':f[1].split(', '),'target':f[2],'ref':f[3].split(', ')})
        elif not definition.startswith('CHECK'):
            c=re.match(r'(\w+)\s+(\w+(?:\(\d+\))?)\b',definition)
            # word boundary after vector(n) is before the opening parenthesis; keep full type.
            c=re.match(r'(\w+)\s+(\w+(?:\(\d+\))?)',definition)
            assert c,definition
            col={'name':c[1], 'type':c[2], 'nullable':not ('NOT NULL' in definition or 'PRIMARY KEY' in definition or 'IDENTITY' in definition), 'identity':'IDENTITY' in definition}
            cols.append(col)
            if 'PRIMARY KEY' in definition:pks.append(c[1])
            if 'UNIQUE' in definition:uqs.append({'cols':[c[1]],'where':None})
            f=re.search(r'REFERENCES (\w+)\((.*?)\)',definition)
            if f:fks.append({'cols':[c[1]],'target':f[1],'ref':f[2].split(', ')})
    for index in re.finditer(r'CREATE UNIQUE INDEX (\w+) ON '+name+r'\((.*?)\) WHERE (.*?);',SQL):
        uqs.append({'cols':index[2].split(', '),'where':index[3]})
    for col in cols:
        if col['name'] in pks:col['nullable']=False
        col['pk']=col['name'] in pks
        col['fk']=any(col['name'] in f['cols'] for f in fks)
        col['uq']=[i+1 for i,u in enumerate(uqs) if col['name'] in u['cols']]
    catalog[name]={'cols':cols,'pk':pks,'uq':uqs,'fk':fks}
assert len(catalog)==16
(CACHE/'schema-catalog.json').write_text(json.dumps(catalog,indent=2))

C={'ink':'#18344B','muted':'#546A7B','line':'#C9D6DF','paper':'#F5F8FA','identity':'#176B75','items':'#244B7A','claims':'#75548D','custody':'#8B642E','ai':'#27695B'}
GROUP={'app_users':'identity','reception_points':'custody','point_staff':'custody','items':'items','verification_questions':'items','stored_objects':'ai','item_images':'ai','claims':'claims','claim_answers':'claims','conversations':'claims','messages':'claims','intake_requests':'custody','custody_events':'custody','ai_jobs':'ai','item_embeddings':'ai','idempotency_keys':'identity'}
DESC={'app_users':'Tài khoản ứng dụng / ánh xạ OIDC','reception_points':'Điểm tiếp nhận trong hệ thống','point_staff':'Phân công và quyền tại từng điểm','items':'Món đồ, nơi giữ hiện tại và trạng thái','stored_objects':'Sổ đối tượng R2 • cả tải dở và chờ xóa','item_images':'Ảnh của món • nguồn, bản che, duyệt','verification_questions':'Bộ câu hỏi hiện tại • 0–3 câu / món','claims':'Yêu cầu nhận đồ • bản chụp người duyệt','claim_answers':'Bằng chứng • chụp câu hỏi tại lúc gửi','conversations':'Chat cho một claim đã được duyệt','messages':'Tin nhắn bền vững • chống gửi trùng','intake_requests':'Yêu cầu gửi vào điểm • chờ nhận thật','custody_events':'Nhật ký nơi giữ / trao trả • chỉ thêm','ai_jobs':'Hàng đợi xử lý • retry, lease, phiên bản','item_embeddings':'Vector text / image • nguồn hiện hành','idempotency_keys':'Chống lặp thao tác nghiệp vụ'}
NOTES={
 'items':['CHECK: đúng 1 nhánh custody_kind (person / point / external).','CHECK: độ chính xác thời gian quyết định các cột ngày/giờ.'],
 'verification_questions':['CHECK: slot từ 1 đến 3; không có hàng = không có câu hỏi.'],
 'claims':['CHECK: claimant khác reviewer; pending chưa có quyết định.'],
 'claim_answers':['Snapshot độc lập; KHÔNG có FK tới verification_questions.'],
 'conversations':["CHECK: approval_status luôn là 'approved'."],
 'messages':['message_sequence là IDENTITY (tự cấp số; NOT NULL).'],
 'custody_events':['CHECK: shape riêng cho registered / received / returned.'],
 'ai_jobs':['CHECK: embed_text không image; việc ảnh bắt buộc image.'],
 'item_embeddings':['CHECK: text không image; image bắt buộc image; dimensions = 2048.'],
 'idempotency_keys':['resource_id đa loại, có chủ đích KHÔNG phải FK.'],
 'stored_objects':['R2 riêng tư: object_kind original / sanitized đều không public.'],
 'item_images':['CHECK: ready cần approved và bản sanitized có provenance.']}

mx=E.Element('mxfile',{'host':'app.diagrams.net','modified':'2026-10-22T00:00:00.000Z','agent':'Findie schema design','version':'24.7.17','type':'device'})
PAGES=[]
class Page:
    def __init__(self,name,w,h,num,title,subtitle):
        self.id=f'p{num}'; self.ids=set(); self.node_bounds={}; self.full_tables=set()
        self.diagram=E.SubElement(mx,'diagram',{'id':self.id,'name':name})
        model=E.SubElement(self.diagram,'mxGraphModel',{'dx':str(w),'dy':str(h),'grid':'1','gridSize':'10','guides':'1','tooltips':'1','connect':'1','arrows':'1','fold':'1','page':'1','pageScale':'1','pageWidth':str(w),'pageHeight':str(h),'math':'0','shadow':'0','background':'#FFFFFF'})
        self.root=E.SubElement(model,'root'); E.SubElement(self.root,'mxCell',{'id':'0'});E.SubElement(self.root,'mxCell',{'id':'1','parent':'0'})
        self.text('eyebrow',f'FINDIE  /  DATABASE DESIGN  /  {num:02d}',60,35,w-120,24,12,C['muted'],True)
        self.text('title',title,60,70,w-120,55,32,C['ink'],True)
        self.text('subtitle',subtitle,60,128,w-120,40,16,C['muted'])
        self.text('footer',f'{num:02d}  •  Nguồn: docs/database/database-schema.sql   |   PostgreSQL + pgvector   |   Thiết kế MVP đề xuất • 22.10.2026',60,h-50,w-120,25,12,C['muted'])
        PAGES.append(self)
    def vertex(self,id,value,x,y,w,h,style,parent='1'):
        assert id not in self.ids,id
        self.ids.add(id)
        cell=E.SubElement(self.root,'mxCell',{'id':id,'value':value,'style':style,'vertex':'1','parent':parent})
        E.SubElement(cell,'mxGeometry',{'x':str(x),'y':str(y),'width':str(w),'height':str(h),'as':'geometry'})
        return cell
    def text(self,id,value,x,y,w,h,font=14,color=None,bold=False,parent='1'):
        return self.vertex(id,value,x,y,w,h,f'text;html=1;strokeColor=none;fillColor=none;whiteSpace=wrap;align=left;verticalAlign=middle;spacing=0;fontFamily=Helvetica;fontSize={font};fontColor={color or C["ink"]};fontStyle={1 if bold else 0};',parent)
    def note(self,id,title,lines,x,y,w,kind='items'):
        lines=[html.escape(t) for t in lines]
        v=f'<b>{html.escape(title)}</b><br><br>'+ '<br>'.join(lines)
        h=60+len(lines)*24
        self.vertex(id,v,x,y,w,h,f'rounded=1;arcSize=5;html=1;whiteSpace=wrap;align=left;verticalAlign=top;spacing=18;fontFamily=Helvetica;fontSize=14;fontColor={C["ink"]};fillColor=#F4F7F9;strokeColor={C["line"]};')
    def table(self,name,x,y,w=520,full=True,summary=None,reference=False):
        data=catalog[name]; color=C[GROUP[name]]; id=self.id+'_'+name
        if full:
            self.full_tables.add(name)
            foot=[]
            for i,u in enumerate(data['uq'],1):
                s=f'UQ{i} ('+', '.join(u['cols'])+')'
                if u['where']:s+=' WHERE '+u['where']
                foot+=textwrap.wrap(s,width=int((w-28)/6.7),break_long_words=False,break_on_hyphens=False)
            for f in data['fk']:
                s='FK ('+', '.join(f['cols'])+') → '+f['target']+'('+', '.join(f['ref'])+')'
                foot+=textwrap.wrap(s,width=int((w-28)/6.7),break_long_words=False,break_on_hyphens=False)
            for n in NOTES.get(name,[]):
                foot+=textwrap.wrap(n,width=int((w-28)/6.7),break_long_words=False,break_on_hyphens=False)
            height=44+len(data['cols'])*29+(len(foot)*19+20 if foot else 0)
        else:
            summary=summary or ['PK '+', '.join(data['pk']),DESC[name]]
            height=44+len(summary)*25+18
        self.node_bounds[id]=(x,y,w,height)
        self.vertex(id,html.escape(name)+('  [ref]' if reference else ''),x,y,w,height,f'shape=swimlane;html=1;startSize=44;horizontal=1;rounded=0;collapsible=0;whiteSpace=wrap;align=left;verticalAlign=middle;spacingLeft=16;fontFamily=Helvetica;fontSize=18;fontStyle=1;fontColor=#FFFFFF;fillColor={color};swimlaneFillColor=#FFFFFF;strokeColor={color};strokeWidth=1.5;')
        if full:
            for i,col in enumerate(data['cols']):
                marks=[]
                if col['pk']:marks.append('PK')
                if col['fk']:marks.append('FK')
                if col['uq']:marks.append('UQ'+','.join(map(str,col['uq'])))
                mark='/'.join(marks)
                # Three native cells per row keep identifiers/types/keys editable and readable.
                row=self.vertex(f'{id}_{col["name"]}', '',0,44+i*29,w,29,f'rect;strokeColor=none;fillColor={"#F2F6F8" if i%2==0 else "#FFFFFF"};',id)
                rid=row.attrib['id']
                self.text(rid+'_name',html.escape(col['name']),12,0,w-205,29,13,C['ink'],False,rid)
                self.text(rid+'_type',col['type']+(' ?' if col['nullable'] else ' !'),w-195,0,130,29,12,C['muted'],False,rid)
                self.text(rid+'_key',mark,w-75,0,70,29,10,color,True,rid)
            if foot:
                fy=44+len(data['cols'])*29
                self.vertex(id+'_constraints','<br>'.join(html.escape(f) for f in foot),0,fy,w,len(foot)*19+20,f'rect;html=1;whiteSpace=wrap;align=left;verticalAlign=top;spacingTop=10;spacingLeft=12;spacingRight=12;spacingBottom=10;fontFamily=Helvetica;fontSize=12;fontColor={C["muted"]};fillColor=#F9FBFC;strokeColor={C["line"]};',id)
        else:
            for i,s in enumerate(summary):self.text(f'{id}_summary_{i}',html.escape(s),14,49+i*25,w-28,25,13,C['muted'],False,id)
        return id
    def edge(self,name,src,tgt,label='',start='one',end='zeromany',via=None,exit=(1,.5),entry=(0,.5),color=None,dashed=False):
        src=self.id+'_'+src; tgt=self.id+'_'+tgt
        assert src in self.ids and tgt in self.ids,(src,tgt)
        arrows={'one':'ERone','many':'ERmany','zeroone':'ERzeroToOne','zeromany':'ERzeroToMany'}
        style=f'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow={arrows[end]};startArrow={arrows[start]};endFill=0;startFill=0;strokeWidth=1.5;strokeColor={color or C["muted"]};fontSize=12;fontFamily=Helvetica;fontColor={C["ink"]};labelBackgroundColor=#FFFFFF;exitX={exit[0]};exitY={exit[1]};entryX={entry[0]};entryY={entry[1]};exitPerimeter=0;entryPerimeter=0;'
        if dashed:style+='dashed=1;'
        edge=E.SubElement(self.root,'mxCell',{'id':self.id+'_e_'+name,'value':html.escape(label),'style':style,'edge':'1','parent':'1','source':src,'target':tgt})
        geo=E.SubElement(edge,'mxGeometry',{'relative':'1','as':'geometry'})
        if via:
            arr=E.SubElement(geo,'Array',{'as':'points'})
            for x,y in via:E.SubElement(arr,'mxPoint',{'x':str(x),'y':str(y)})
        return edge

# 01: the complete schema on one canvas; domain pages keep their focused layouts.
p=Page('01 · Tổng quan',3560,3600,1,'ERD tổng quan · Đầy đủ 16 bảng và 164 cột','Mỗi bảng có tên cột, kiểu dữ liệu, NULL, PK/FK và UNIQUE · Phóng to để đọc từng miền dữ liệu.')
columns=[
 ('identity','TÀI KHOẢN & ĐIỂM',['app_users','point_staff','reception_points','intake_requests']),
 ('items','MÓN ĐỒ & LỊCH SỬ',['items','verification_questions','custody_events','idempotency_keys']),
 ('claims','YÊU CẦU & CHAT',['claims','claim_answers','conversations','messages']),
 ('ai','ẢNH R2 & AI',['item_images','stored_objects','ai_jobs','item_embeddings'])
]
for i,(kind,label,names) in enumerate(columns):
    x=80+i*850
    p.text('group'+str(i),label,x,195,650,28,13,C[kind],True)
    y=260
    for name in names:
        p.table(name,x,y,650)
        y+=p.node_bounds[p.id+'_'+name][3]+130

# Long relationships run in the gutters rather than across unrelated tables.
user=p.node_bounds['p1_app_users'];item=p.node_bounds['p1_items'];claim=p.node_bounds['p1_claims']
image=p.node_bounds['p1_item_images'];chat=p.node_bounds['p1_conversations']
event=p.node_bounds['p1_custody_events'];job=p.node_bounds['p1_ai_jobs'];embedding=p.node_bounds['p1_item_embeddings']
p.edge('author','app_users','items','posted_by',exit=(1,22/user[3]),entry=(0,22/item[3]))
p.edge('staff_user','app_users','point_staff','1 : 0..N',exit=(.5,1),entry=(.5,0))
p.edge('staff_point','reception_points','point_staff','1 : 0..N',exit=(.5,0),entry=(.5,1))
p.edge('intake_point','reception_points','intake_requests','điểm đích · 1 : 0..N',exit=(.5,1),entry=(.5,0))
p.edge('question','items','verification_questions','1 : 0..3',exit=(.5,1),entry=(.5,0))
p.edge('claims','items','claims','1 : 0..N',exit=(1,22/item[3]),entry=(0,22/claim[3]))
p.edge('answers','claims','claim_answers','snapshot · 1 : 0..3',exit=(.5,1),entry=(.5,0))
p.edge('chat','claims','conversations','approved · 0..1',exit=(1,.65),entry=(1,.3),end='zeroone',via=[(2530,claim[1]+claim[3]*.65),(2530,chat[1]+chat[3]*.3)])
p.edge('messages','conversations','messages','1 : 0..N',exit=(.5,1),entry=(.5,0))
p.edge('custody','items','custody_events','1 : 0..N',exit=(1,.8),entry=(1,.25),via=[(1680,item[1]+item[3]*.8),(1680,event[1]+event[3]*.25)])
p.edge('intake_event','intake_requests','custody_events','received · 0..1',exit=(1,.5),entry=(0,.65),start='zeroone',end='zeroone')
p.edge('item_image','items','item_images','1 : 0..N',exit=(.8,0),entry=(.2,0),via=[(item[0]+item[2]*.8,235),(image[0]+image[2]*.2,235)])
p.edge('original','stored_objects','item_images','original · 1 : 0..1',exit=(.25,0),entry=(.25,1),end='zeroone')
p.edge('sanitized','stored_objects','item_images','sanitized · 0..1 : 0..1',exit=(.75,0),entry=(.75,1),start='zeroone',end='zeroone')
p.edge('imagejob','item_images','ai_jobs','job ảnh',exit=(1,.3),entry=(1,.2),start='zeroone',via=[(3380,image[1]+image[3]*.3),(3380,job[1]+job[3]*.2)])
p.edge('imageembedding','item_images','item_embeddings','vector ảnh',exit=(1,.7),entry=(1,.2),start='zeroone',via=[(3470,image[1]+image[3]*.7),(3470,embedding[1]+embedding[3]*.2)])
bottom=max(y+h for x,y,w,h in p.node_bounds.values())
p.note('legend','Đọc sơ đồ',[
 'Mỗi hàng là một cột trong DDL: tên cột | kiểu dữ liệu và NULL | ký hiệu khóa.',
 '! = NOT NULL; ? = nullable; PK = khóa chính; FK = khóa ngoại; UQn = nhóm UNIQUE được liệt kê dưới bảng.',
 'Các cột mang cùng UQn tạo một khóa ghép; WHERE giới hạn phạm vi duy nhất. CHECK đầy đủ xem DDL.',
 '1 = đúng một; 0..1 = tùy chọn; 0..N = không hoặc nhiều; 0..3 được giới hạn bằng slot.',
 'Đường nối thể hiện quan hệ chính; mọi FK đều được ghi dưới bảng. resource_id của idempotency_keys không phải FK.'
],80,bottom+80,3400)
height=bottom+360
model=p.diagram.find('mxGraphModel')
model.set('dy',str(height));model.set('pageHeight',str(height))
p.root.find("mxCell[@id='footer']/mxGeometry").set('y',str(height-50))
assert p.full_tables==set(catalog), 'Overview must show every table in full'

# 02: identity, inventory, current questions and request deduplication.
p=Page('02 · Tài khoản và món đồ',2200,1810,2,'Tài khoản, món đồ & câu hỏi','! = NOT NULL   ·   ? = có thể NULL   ·   PK = khóa chính   ·   FK = khóa ngoại   ·   UQn = nhóm duy nhất ghi dưới bảng.')
p.table('app_users',60,230,540)
p.table('reception_points',760,230,540)
p.table('items',1520,230,610)
p.table('point_staff',60,720,540)
p.table('verification_questions',760,730,540)
p.table('idempotency_keys',760,1160,540)
p.edge('staffuser','app_users','point_staff','1 : 0..N',exit=(.5,1),entry=(.5,0),end='zeromany')
p.edge('staffpoint','reception_points','point_staff','1 : 0..N',exit=(0,.8),entry=(1,.25),end='zeromany',via=[(680,430),(680,790)])
p.edge('author','app_users','items','posted_by · 1 : 0..N',exit=(.9,0),entry=(.2,0),end='zeromany',via=[(545,200),(1642,200)])
p.edge('pointcustody','reception_points','items','holder_point_id · 0..1 : 0..N',start='zeroone',end='zeromany',exit=(1,.5),entry=(0,.2))
p.edge('question','items','verification_questions','1 : 0..3',end='zeromany',exit=(0,.62),entry=(1,.5))
p.edge('dedupe','app_users','idempotency_keys','actor · 1 : 0..N',end='zeromany',exit=(1,.8),entry=(0,.2),via=[(650,480),(650,1240)])
p.note('inventoryrules','Quy tắc nghiệp vụ cần đọc cùng DDL',[
 'items.custody_kind chọn đúng một nơi giữ: cá nhân, điểm trong hệ thống hoặc nơi bên ngoài.',
 'holder_user_id → app_users(id), tùy chọn theo nhánh person; posted_by luôn bắt buộc.',
 'Sau returned, nơi giữ trên items là nơi cuối cùng trước khi trả; không biến người nhận thành người giữ.',
 'Tối đa 3 câu hỏi hiện tại. Claim chụp câu hỏi riêng; sửa câu hỏi không sửa bằng chứng đã gửi.',
 'point_staff không phải vai trò toàn hệ thống: quyền bị giới hạn theo point_id và revoked_at.',
 'ON DELETE RESTRICT cho các FK. Xác thực, phân quyền và kiểm tra chuyển trạng thái thuộc .NET.'
],1430,1390,700)
p.note('legend2','Khóa và tính rỗng',[
 'PK ghép: mọi cột đánh dấu PK cùng tạo một khóa.',
 'UQn là nhóm cột, không phải từng cột độc lập.',
 'UQn có WHERE chỉ áp dụng cho các hàng thỏa điều kiện.',
 '? chỉ mô tả NULL ở cột; CHECK có thể buộc giá trị theo trạng thái.',
 'Các FK phụ được ghi đầy đủ dưới từng bảng, kể cả không có đường nối.'
],60,1280,540)

# 03: claims are immutable participants; approval-backed one-to-one chat.
p=Page('03 · Yêu cầu nhận và chat',2240,1660,3,'Yêu cầu nhận đồ & hội thoại','Claim giữ người yêu cầu / người duyệt tại thời điểm gửi · Hội thoại chỉ tồn tại cho claim approved.')
p.table('claims',60,230,630)
p.table('claim_answers',850,230,560)
p.table('conversations',850,780,560)
p.table('messages',1580,780,600)
p.table('app_users',1580,230,600,False,['PK id','FK: claimant / reviewer / decided_by','FK: sender_user_id'],True)
p.table('items',60,1160,630,False,['PK id','Claim thuộc đúng một món đồ','source_custody_version chụp lúc gửi'],True)
p.edge('answer','claims','claim_answers','1 : 0..3',exit=(1,.23),entry=(0,.5),end='zeromany')
p.edge('conversation','claims','conversations','(id, status) → (claim_id, approval_status)',exit=(1,.72),entry=(0,.45),end='zeroone',via=[(770,730),(770,870)])
p.edge('messages','conversations','messages','1 : 0..N',end='zeromany')
p.edge('item','items','claims','1 : 0..N',exit=(.5,0),entry=(.5,1),end='zeromany')
p.note('claimrules','Không tạo quan hệ giả từ snapshot',[
 'claim_answers.question_text_snapshot chụp bộ câu hỏi tại lúc gửi.',
 'Không có FK từ claim_answers sang verification_questions.',
 'answer_text có thể NULL; chính sách bắt buộc trả lời còn phải chốt.',
 'Claim có thể có 0 câu trả lời khi món không đặt câu hỏi.'
],850,510,560)
p.note('chatrules','Chat đúng hai bên; ghi xong mới phát SignalR',[
 "conversations.claim_id là PK; FK ghép bắt buộc approval_status = 'approved'.",
 'Một claim có tối đa một chat; người tham gia lấy từ claimant và reviewer.',
 'FK sender chỉ xác nhận tài khoản tồn tại. .NET kiểm tra sender là một trong hai bên.',
 'Khóa hàng conversation trước INSERT; commit rồi phát sự kiện để lịch sử không bỏ sót sequence.',
 'Mã gửi lại duy nhất theo hội thoại + người gửi + client_message_id.'
],60,1380,2120)

# 04: request is separate from physical custody and immutable history.
p=Page('04 · Tiếp nhận và trao trả',2240,1840,4,'Tiếp nhận thực tế & lịch sử trao trả','Pending không thay nơi giữ · Bàn giao cập nhật món, yêu cầu và sự kiện trong cùng giao dịch.')
p.table('reception_points',60,230,540,False,['PK id','Điểm đích phải active','Nhân viên có quyền theo point_staff'],True)
p.table('app_users',60,490,540,False,['PK id','Actor / requester / người nhận nếu có'],True)
p.table('point_staff',60,760,540)
p.table('items',760,230,580,False,['PK id','Nơi giữ hiện tại + custody_version','lifecycle: active / returned'],True)
p.table('intake_requests',760,570,580)
p.table('custody_events',1540,230,630)
p.table('claims',760,1330,580,False,['PK id; UQ (id, item_id)','Có thể liên kết sự kiện trả cho đúng món','Trả tại điểm không bắt buộc có claim'],True)
p.edge('staffpoint','reception_points','point_staff','1 : 0..N',exit=(0,.5),entry=(0,.2),end='zeromany',via=[(30,300),(30,820)])
p.edge('staffuser','app_users','point_staff','1 : 0..N',exit=(.5,1),entry=(.5,0),end='zeromany')
p.edge('itemintake','items','intake_requests','1 : 0..N',exit=(.5,1),entry=(.5,0),end='zeromany')
p.edge('itemevent','items','custody_events','1 : 0..N',end='zeromany')
p.edge('intakeevent','intake_requests','custody_events','(id, item_id) · 0..1 : 0..1',exit=(1,.42),entry=(0,.6),start='zeroone',end='zeroone')
p.edge('claimevent','claims','custody_events','(id, item_id) · claim tùy chọn',exit=(1,.5),entry=(0,.92),start='zeroone',end='zeromany',via=[(1450,1410),(1450,1080)])
p.note('custodyrules','Ràng buộc lịch sử và quyền thao tác',[
 'intake_requests.target_point_id → reception_points(id). pending / rejected không đổi nơi giữ.',
 'FK ghép kèm item_id chặn liên kết intake hoặc claim thuộc món khác.',
 'Mỗi item có tối đa một event registered và một event returned (partial UNIQUE).',
 'intake_request_id duy nhất: một yêu cầu nhận thực tế có tối đa một sự kiện.',
 'from_custody / to_custody là snapshot JSON; không thay thế FK nơi giữ hiện tại.',
 'Nhận tại điểm có thể không có tài khoản người nhận; recipient_user_id được phép NULL.',
 'Actor, quyền nhân viên còn hiệu lực và giao dịch nguyên tử do .NET kiểm tra.'
],60,1520,2110)

# 05: object lifecycle and versioned AI jobs, not public URLs.
p=Page('05 · R2 và xử lý AI',2800,1930,5,'Ảnh R2 riêng tư & dữ liệu AI','Qwen3-VL-4B-Instruct → vùng cần che · OpenCV → bản che · Qwen3-VL-Embedding-2B → vector 2048 chiều.')
p.table('items',60,250,540,False,['PK id','source_version văn bản = items.content_version','Mỗi bảng AI luôn FK về item_id'],True)
p.table('stored_objects',60,660,540)
p.table('item_images',760,250,580)
p.table('ai_jobs',1450,250,610)
p.table('item_embeddings',2180,250,560)
p.edge('itemimage','items','item_images','1 : 0..N',end='zeromany',exit=(1,.5),entry=(0,.15))
p.edge('original','stored_objects','item_images','original · 1 : 0..1',exit=(1,.24),entry=(0,.4),end='zeroone',via=[(670,850),(670,580)])
p.edge('sanitized','stored_objects','item_images','sanitized · 0..1',start='zeroone',end='zeroone',exit=(1,.55),entry=(0,.6),via=[(710,1080),(710,750)])
p.edge('imagejobs','item_images','ai_jobs','(id, item_id) · 0..1 : 0..N',start='zeroone',end='zeromany',exit=(1,.3),entry=(0,.2))
p.edge('imageembeddings','item_images','item_embeddings','(id, item_id) · 0..1 : 0..N',start='zeroone',end='zeromany',exit=(1,.9),entry=(0,.9),via=[(1390,1120),(1390,1550),(2120,1550),(2120,1090)])
p.note('privacy','Không lưu URL công khai hoặc URL có chữ ký vào DB',[
 'stored_objects là metadata; byte ảnh nằm ở Cloudflare R2.',
 'Cả original và sanitized đều ở bucket riêng tư; không bật r2.dev.',
 '.NET phục vụ bản đã duyệt qua API; URL ký chỉ là phương án mở rộng.',
 'Owner / reviewer → app_users(id), ghi ở FK dưới bảng.',
 'Lưu object_key trước upload; chỉ xóa metadata sau khi dọn R2 thành công.'
],760,1370,580)
p.note('airules','Kết quả AI phải khớp nguồn trước khi lưu',[
 'source_version + source_sha256 + model_id + model_revision + processing_profile xác định đầu vào.',
 'image_id NULL chỉ dành cho text. FK ghép (image_id, item_id) buộc ảnh thuộc đúng món.',
 'Job giữ lease_token / lease_until; retry hữu hạn và bỏ kết quả khi nguồn hoặc lease đã đổi.',
 'Vector ảnh được tạo từ bản che đã duyệt. Không embedding ảnh gốc hoặc bằng chứng claim.',
 'vector(2048): MVP tìm cosine chính xác; chưa tạo HNSW/IVFFlat cho kiểu vector 2048 chiều.',
 'Chỉ tìm bài published / active, nguồn hiện hành và ảnh ready / approved chưa retired.',
 'Job và vector không có FK trực tiếp với nhau; liên kết được kiểm tra bằng nguồn / version / model / profile.'
],1450,1600,1280)
p.note('keylegend','Đọc đầy đủ các khóa',[
 '! NOT NULL; ? nullable; PK khóa chính; FK khóa ngoại.',
 'UQn là nhóm cột được liệt kê dưới bảng; WHERE là unique có điều kiện.',
 'Mọi FK nghiệp vụ ON DELETE RESTRICT; DDL là nguồn chuẩn cho CHECK đầy đủ.'
],60,1730,1280)

# Self-check: every SQL column and key declaration has a native cell in at least one detail page.
all_tables=set().union(*(p.full_tables for p in PAGES))
assert all_tables==set(catalog),(all_tables,set(catalog))
for name,data in catalog.items():
    owners=[p for p in PAGES if name in p.full_tables]
    for c in data['cols']:
        assert any(f'{p.id}_{name}_{c["name"]}' in p.ids for p in owners),(name,c)
for p in PAGES:
    assert all(c.get('source') in p.ids and c.get('target') in p.ids for c in p.root.findall('mxCell') if c.get('edge')=='1')
E.indent(mx,space='  ')
E.ElementTree(mx).write(OUT,encoding='utf-8',xml_declaration=True)
print(f'Wrote {OUT}: {len(PAGES)} pages, {len(catalog)} tables, {sum(len(t["cols"]) for t in catalog.values())} columns')
for p in PAGES:
    maxy=max(y+h for x,y,w,h in p.node_bounds.values())
    print(p.diagram.get('name'),'tables bottom',maxy)
