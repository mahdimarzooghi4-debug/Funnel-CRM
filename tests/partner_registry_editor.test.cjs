const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const source=execFileSync('python',['-c','from funnel_crm.web.crm_channel_partners_workspace import _SCRIPT; print(_SCRIPT)'],{encoding:'utf8'});
function harness(fail=false){
 const nodes=new Map();
 function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',disabled:false,classList:{toggle(){}},addEventListener(){},focus(){},reset(){for(const [key,n] of nodes)if(key.startsWith('partner-'))n.value='';}});return nodes.get(id)}
 node('workspace').value='workspace-a';node('unit').value='unit-a';
 const calls=[];
 const code=source.replace('$("refresh").addEventListener("click",load);','globalThis.editor={savePartner,editPartner,resetPartner,partnerQuery};load=async()=>{};$("refresh").addEventListener("click",load);').replace('ws.addEventListener("change",init);init();','ws.addEventListener("change",init);');
 const context={document:{getElementById:node},Intl,URLSearchParams,fetch:async(path,options)=>{calls.push({path,options});return {ok:!fail,json:async()=>fail?{detail:'changed'}:{id:'created'}}}};
 vm.runInNewContext(code,context);
 for(const key of ['name','type','status','contact_name','email','phone','territory','notes'])node('partner-'+key).value='';
 node('partner-name').value=' شریک ';node('partner-type').value='agency';node('partner-status').value='active';
 return {node,calls,editor:context.editor};
}
test('create sends selected scope and trimmed data and prevents duplicate submissions',async()=>{
 const h=harness();const first=h.editor.savePartner({preventDefault(){}});await h.editor.savePartner({preventDefault(){}});await first;
 assert.equal(h.calls.length,1);const call=h.calls[0];assert.equal(call.options.method,'POST');assert.equal(call.options.headers['X-Workspace-ID'],'workspace-a');assert.equal(JSON.parse(call.options.body).organization_unit_id,'unit-a');assert.equal(JSON.parse(call.options.body).name,'شریک');assert.equal(h.node('partner-save').disabled,false);
});
test('edit sends version; failed write retains input and restores controls',async()=>{
 const h=harness(true);h.editor.editPartner({id:'partner-a',version:7,name:'نام جدید',partner_type:'agency',status:'active'});await h.editor.savePartner({preventDefault(){}});
 assert.equal(h.calls[0].options.method,'PATCH');assert.equal(JSON.parse(h.calls[0].options.body).expected_version,7);assert.equal(h.node('partner-name').value,'نام جدید');assert.match(h.node('partner-message').textContent,/ذخیره انجام نشد/);assert.equal(h.node('workspace').disabled,false);
});
test('changing scope invalidates an earlier edit without sending a write',async()=>{
 const h=harness();h.editor.editPartner({id:'partner-a',version:7,name:'نام',partner_type:'agency',status:'active'});h.node('unit').value='unit-b';await h.editor.savePartner({preventDefault(){}});assert.equal(h.calls.length,0);
});

test('partner filters encode literal search and organization scope',()=>{
 const h=harness();h.node('partner-search').value='  شرکت % &  ';h.node('partner-filter-type').value='agency';h.node('partner-filter-status').value='active';
 const q=h.editor.partnerQuery();assert.equal(q.get('search'),'شرکت % &');assert.equal(q.get('organization_unit_id'),'unit-a');assert.equal(q.get('partner_type'),'agency');assert.equal(q.get('status'),'active');assert.equal(q.get('limit'),'50');assert.equal(q.get('offset'),'0');
});
