
initTheme();
let currentUser=null, groups=[], activeGroup=null, activeMembers=[], activeExpenses=[], activeBalances=[];
const $ = id => document.getElementById(id);
const esc = value => escapeHtml(value == null ? '' : String(value));
const today = todayISO();
const toNum = value => Number(value || 0);
const moneySafe = value => typeof money === 'function' ? money(toNum(value)) : '₹' + toNum(value).toFixed(2);
function showError(message){ $('pageError').textContent=message || 'Something went wrong.'; $('pageError').hidden=false; }
function clearError(){ $('pageError').hidden=true; $('pageError').textContent=''; }
function initials(name){ return String(name||'?').trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase() || '?'; }
function dateLabel(value){ return typeof formatDate==='function' ? formatDate(value) : String(value||''); }
function currentUserId(){ return Number(currentUser?.id ?? currentUser?.user_id ?? 0); }

async function init(){
  try{
    currentUser=await requireAuth();
    buildNav('split-expenses',currentUser);
    await loadGroups();
  }catch(error){ showError(error.message || 'Unable to load Split Expenses.'); }
}

async function loadGroups(openId=null){
  clearError();
  try{
    const response=await API_CLIENT.get('/split-groups');
    groups=Array.isArray(response)?response:(response.groups||[]);
    $('groupCount').textContent=groups.length;
    $('groupsList').innerHTML=groups.length?groups.map(group=>`
      <button type="button" class="group-choice ${activeGroup && Number(activeGroup.id)===Number(group.id)?'active':''}" data-group-id="${Number(group.id)}">
        <span class="group-choice-top"><strong>${esc(group.name)}</strong><span>›</span></span>
        <span class="muted">${Number(group.member_count||0)} people · ${Number(group.expense_count||0)} shared expenses</span>
      </button>`).join(''):'<div class="empty-box">No groups yet. Create your first group.</div>';
    $('groupsList').querySelectorAll('[data-group-id]').forEach(button=>button.addEventListener('click',()=>openGroup(Number(button.dataset.groupId))));
    const wanted=openId || activeGroup?.id;
    if(wanted && groups.some(group=>Number(group.id)===Number(wanted))) await openGroup(Number(wanted));
    else if(!activeGroup) $('groupWorkspace').innerHTML='<div class="card empty-box"><div style="font-size:2rem">👥</div><strong>Create your first group</strong><p class="muted">Add friends by name and start recording shared spending.</p></div>';
  }catch(error){ showError(error.message || 'Could not load groups.'); $('groupsList').innerHTML='<div class="empty-box">Could not load groups. Check your connection and try again.</div>'; }
}

async function openGroup(id){
  clearError();
  try{
    activeGroup=await API_CLIENT.get(`/split-groups/${id}`);
    activeMembers=activeGroup.members||[];
    renderWorkspace();
    await refreshGroupData();
    document.querySelectorAll('[data-group-id]').forEach(button=>button.classList.toggle('active',Number(button.dataset.groupId)===Number(id)));
  }catch(error){ showError(error.message || 'Could not open this group.'); }
}

function renderWorkspace(){
  const owner = activeGroup.my_role==='owner';
  $('groupWorkspace').innerHTML=`
    <section class="card">
      <div class="section-head"><div><h2>${esc(activeGroup.name)}</h2><p class="muted">${esc(activeGroup.description||'Shared spending group')}</p></div><span class="pill">${activeMembers.length} people</span></div>
      <div class="split-grid three" id="groupStats">
        <div class="stat-tile"><div class="stat-label">Total shared spending</div><div class="stat-number" id="gTotal">₹0.00</div></div>
        <div class="stat-tile"><div class="stat-label">Shared expenses</div><div class="stat-number" id="gExpenseCount">0</div></div>
        <div class="stat-tile"><div class="stat-label">Your net balance</div><div class="stat-number" id="gMyBalance">₹0.00</div></div>
      </div>
      <div class="section-separator"></div>
      <div class="section-head"><h3>People in this group</h3><span class="muted">Add names — no email required</span></div>
      <div id="membersBox" class="member-list"></div>
      ${owner?`<form id="addMemberForm" class="split-row" style="margin-top:14px"><div class="field"><label for="memberName">Add a person's name</label><input id="memberName" maxlength="100" placeholder="e.g. Arun Kumar" required></div><button class="btn btn-secondary" type="submit">＋ Add person</button></form>`:''}
    </section>

    <section class="card">
      <div class="section-head"><div><h3>＋ Record group spending</h3><p class="muted">Enter the bill and choose how to share it.</p></div></div>
      <form id="sharedExpenseForm" class="split-stack" style="gap:14px">
        <div class="split-row">
          <div class="field"><label for="expTitle">What was it for?</label><input id="expTitle" maxlength="150" placeholder="e.g. Dinner, groceries, cab" required></div>
          <div class="field"><label for="expAmount">Total bill (₹)</label><input id="expAmount" type="number" min="0.01" step="0.01" placeholder="0.00" required></div>
        </div>
        <div class="split-row">
          <div class="field"><label for="expDate">Date</label><input id="expDate" type="date" value="${today}" required></div>
          <div class="field"><label for="expCategory">Category</label><select id="expCategory"><option>Food</option><option>Transport</option><option>Groceries</option><option>Shopping</option><option>College</option><option>Hostel</option><option>Bills</option><option>Entertainment</option><option>Other</option></select></div>
        </div>
        <div class="split-row">
          <div class="field"><label for="paidBy">Who paid the bill?</label><select id="paidBy"></select></div>
          <div class="field"><label for="splitMethod">How should it be split?</label><select id="splitMethod"><option value="equal">Equally</option><option value="custom">Enter each person's amount</option><option value="percentage">By percentage</option></select></div>
        </div>
        <div class="field"><label>Who shared this expense?</label><div id="participants" class="person-checks"></div><span class="muted">Select only the people who should pay a share of this bill.</span></div>
        <div id="splitValues"></div>
        <div id="splitPreview" class="preview-panel"><strong>Split preview</strong><p class="muted">Enter a bill amount and select participants to preview each person's share.</p></div>
        <div class="field"><label for="expDescription">Note <span class="muted">(optional)</span></label><textarea id="expDescription" rows="2" maxlength="1000" placeholder="Add a note about this expense"></textarea></div>
        <div class="split-row"><button type="submit" class="btn btn-primary" id="saveSharedExpenseBtn">Save shared expense</button><button type="reset" class="btn btn-secondary" id="resetExpenseBtn">Clear form</button></div>
      </form>
    </section>

    <section class="card"><div class="section-head"><div><h3>💸 Who owes whom?</h3><p class="muted">Positive means this person should receive money. Negative means this person owes money.</p></div></div><div id="balancesBox" class="member-list"></div><div class="section-separator"></div><div class="section-head"><h3>Suggested settlements</h3></div><div id="settlementSuggestions"></div></section>

    <section class="card"><div class="section-head"><h3>📋 Shared spending history</h3><span class="pill" id="historyCount">0 records</span></div><div id="expenseHistory" class="split-stack"></div></section>
    <section class="card"><div class="section-head"><h3>✅ Settlement history</h3></div><div id="settlementHistory" class="split-stack"></div></section>`;

  $('addMemberForm')?.addEventListener('submit',addMember);
  $('sharedExpenseForm').addEventListener('submit',saveSharedExpense);
  $('splitMethod').addEventListener('change',()=>{renderSplitInputs();renderPreview();});
  $('participants').addEventListener('change',()=>{renderSplitInputs();renderPreview();});
  $('expAmount').addEventListener('input',renderPreview);
  $('newGroupFocus').addEventListener('click',()=>{$('groupName').focus();$('createGroupCard').scrollIntoView({behavior:'smooth',block:'center'});});
  $('sharedExpenseForm').addEventListener('reset',()=>setTimeout(()=>{ $('expDate').value=today; renderSplitInputs(); renderPreview(); },0));
  renderMemberControls();renderSplitInputs();renderPreview();
}

function renderMemberControls(){
  $('membersBox').innerHTML=activeMembers.map(person=>`
    <div class="member-card"><div class="avatar">${esc(initials(person.name))}</div><div class="member-info"><div class="member-name">${esc(person.name)}</div><div class="muted">${person.role==='owner'?'Group owner':'Group member'}</div></div>${person.role==='owner'?'<span class="pill">You</span>':`<button class="btn btn-secondary small-button remove-member" data-person-id="${person.person_id}" title="Remove member" aria-label="Remove ${esc(person.name)}">✕</button>`}</div>`).join('') || '<div class="empty-box">No members yet.</div>';
  $('paidBy').innerHTML=activeMembers.map(person=>`<option value="${person.person_id}">${esc(person.name)}${person.role==='owner'?' (You)':''}</option>`).join('');
  $('participants').innerHTML=activeMembers.map(person=>`<label class="person-check"><input type="checkbox" value="${person.person_id}" checked><span>${esc(person.name)}</span></label>`).join('');
  document.querySelectorAll('.remove-member').forEach(button=>button.addEventListener('click',()=>removeMember(Number(button.dataset.personId))));
}
function selectedIds(){return [...$('participants').querySelectorAll('input:checked')].map(input=>Number(input.value));}
function renderSplitInputs(){
  const method=$('splitMethod').value, ids=selectedIds(), participants=activeMembers.filter(person=>ids.includes(Number(person.person_id)));
  if(method==='equal'){$('splitValues').innerHTML='<div class="split-help">Equal split: the bill is divided among selected people. Any extra paise are distributed so the shares exactly match the bill.</div>';return;}
  $('splitValues').innerHTML=`<div class="field"><label>${method==='custom'?'Enter each member amount (₹)':'Enter each member percentage (%)'}</label><div class="split-values">${participants.map(person=>`<div class="split-value-row"><span>${esc(person.name)}</span><input class="form-control split-value" type="number" min="0" step="${method==='custom'?'0.01':'0.01'}" data-person-id="${person.person_id}" placeholder="${method==='custom'?'0.00':'0%'}"></div>`).join('')}</div><p class="muted">${method==='custom'?'All amounts must add up exactly to the total bill.':'All percentages must add up to exactly 100%.'}</p></div>`;
  document.querySelectorAll('.split-value').forEach(input=>input.addEventListener('input',renderPreview));
}
function calculatePreview(){
  const totalRaw=Number($('expAmount').value), totalCents=Math.round(totalRaw*100), ids=selectedIds(), method=$('splitMethod').value;
  if(!Number.isFinite(totalRaw)||totalRaw<=0||!ids.length)return {error:'Enter a bill amount and select at least one person.'};
  const people=activeMembers.filter(person=>ids.includes(Number(person.person_id)));
  let shares=[];
  if(method==='equal'){
    const base=Math.floor(totalCents/ids.length), remainder=totalCents%ids.length;
    shares=ids.slice().sort((a,b)=>a-b).map((id,index)=>({person_id:id,amount:(base+(index<remainder?1:0))/100}));
  }else{
    const inputs=[...document.querySelectorAll('.split-value')];
    if(inputs.length!==ids.length)return {error:'Enter a value for each selected person.'};
    const values=inputs.map(input=>({person_id:Number(input.dataset.personId),value:Number(input.value)}));
    if(values.some(item=>!Number.isFinite(item.value)||item.value<0))return {error:'Enter valid non-negative split values.'};
    if(method==='custom'){
      const sumCents=values.reduce((sum,item)=>sum+Math.round(item.value*100),0);
      if(values.some(item=>Math.abs(item.value*100-Math.round(item.value*100))>0.00001))return {error:'Custom amounts can have at most two decimal places.'};
      if(sumCents!==totalCents)return {error:`Shares total ₹${(sumCents/100).toFixed(2)}. They must equal ₹${(totalCents/100).toFixed(2)}.`};
      shares=values.map(item=>({person_id:item.person_id,amount:Math.round(item.value*100)/100}));
    }else{
      const percentTotal=Math.round(values.reduce((sum,item)=>sum+item.value,0)*100)/100;
      if(Math.abs(percentTotal-100)>0.00001)return {error:`Percentages currently total ${percentTotal}%. They must equal 100%.`};
      const raw=values.map(item=>({person_id:item.person_id,raw:totalCents*item.value/100}));
      const floored=raw.map(item=>({...item,cents:Math.floor(item.raw)}));
      let remaining=totalCents-floored.reduce((sum,item)=>sum+item.cents,0);
      floored.sort((a,b)=>(b.raw-b.cents)-(a.raw-a.cents)||a.person_id-b.person_id);
      for(let index=0;index<remaining;index++)floored[index%floored.length].cents++;
      shares=floored.map(item=>({person_id:item.person_id,amount:item.cents/100}));
    }
  }
  const shareTotal=Math.round(shares.reduce((sum,item)=>sum+item.amount,0)*100);
  if(shareTotal!==totalCents)return {error:'The shares do not equal the full bill. Please check the amounts.'};
  return {shares,people,total:totalCents/100};
}
function renderPreview(){
  const preview=$('splitPreview');if(!preview)return;
  const result=calculatePreview();
  if(result.error){preview.innerHTML=`<strong>Split preview</strong><p class="muted">${esc(result.error)}</p>`;return;}
  const byId=new Map(result.people.map(person=>[Number(person.person_id),person]));
  preview.innerHTML=`<div class="section-head"><strong>Preview — ${moneySafe(result.total)}</strong><span class="pill">${result.shares.length} people</span></div>${result.shares.map(share=>`<div class="preview-line"><span>${esc(byId.get(share.person_id)?.name||'Member')}</span><strong>${moneySafe(share.amount)}</strong></div>`).join('')}<div class="preview-line"><strong>Total of shares</strong><strong>${moneySafe(result.shares.reduce((sum,item)=>sum+item.amount,0))}</strong></div>`;
}

async function addMember(event){
  event.preventDefault();clearError();const name=$('memberName').value.trim();if(!name)return;
  try{await API_CLIENT.post(`/split-groups/${activeGroup.id}/members`,{name});showToast(`${name} added to the group.`,'success');await openGroup(activeGroup.id);}
  catch(error){showError(error.message||'Could not add this person.');}
}
async function removeMember(personId){
  const person=activeMembers.find(item=>Number(item.person_id)===personId);if(!person)return;
  if(!confirm(`Remove ${person.name} from this group? People with recorded expenses or settlements cannot be removed.`))return;
  try{await API_CLIENT.del(`/split-groups/${activeGroup.id}/members/${personId}`);showToast('Member removed.','success');await openGroup(activeGroup.id);}
  catch(error){showError(error.message||'Could not remove this member.');}
}
async function saveSharedExpense(event){
  event.preventDefault();clearError();const result=calculatePreview();if(result.error){showError(result.error);return;}
  const method=$('splitMethod').value;
  const splits=method==='equal'?[]:[...document.querySelectorAll('.split-value')].map(input=>({person_id:Number(input.dataset.personId),...(method==='custom'?{amount:input.value}:{percentage:input.value})}));
  const payload={title:$('expTitle').value.trim(),total_amount:$('expAmount').value,expense_date:$('expDate').value,category:$('expCategory').value,paid_by_person_id:Number($('paidBy').value),split_method:method,participant_person_ids:selectedIds(),splits,description:$('expDescription').value.trim()};
  const button=$('saveSharedExpenseBtn');button.disabled=true;button.textContent='Saving…';
  try{await API_CLIENT.post(`/split-groups/${activeGroup.id}/expenses`,payload);showToast('Shared expense saved.','success');$('sharedExpenseForm').reset();await refreshGroupData();await loadGroups(activeGroup.id);}
  catch(error){showError(error.message||'Could not save shared expense.');}
  finally{button.disabled=false;button.textContent='Save shared expense';}
}
async function refreshGroupData(){
  const [detail,expenses,balanceResponse,settlements]=await Promise.all([
    API_CLIENT.get(`/split-groups/${activeGroup.id}`),
    API_CLIENT.get(`/split-groups/${activeGroup.id}/expenses`),
    API_CLIENT.get(`/split-groups/${activeGroup.id}/balances`),
    API_CLIENT.get(`/split-groups/${activeGroup.id}/settlements`)
  ]);
  activeGroup=detail;activeMembers=detail.members||[];activeExpenses=Array.isArray(expenses)?expenses:[];activeBalances=balanceResponse.balances||[];
  renderMemberControls();
  renderSplitInputs();
  renderPreview();
  const total=activeExpenses.reduce((sum,item)=>sum+Number(item.total_amount||0),0);
  const me=activeMembers.find(person=>Number(person.user_id)===currentUserId() && person.role==='owner');
  const myBalance=me?activeBalances.find(item=>Number(item.person_id)===Number(me.person_id)):null;
  $('gTotal').textContent=moneySafe(total);$('gExpenseCount').textContent=activeExpenses.length;
  $('gMyBalance').textContent=myBalance?moneySafe(Math.abs(myBalance.balance)):'—';$('gMyBalance').className='stat-number '+(myBalance?.balance>0?'positive':myBalance?.balance<0?'negative':'');
  $('balancesBox').innerHTML=activeBalances.length?activeBalances.map(item=>`<div class="member-card"><div class="avatar">${esc(initials(item.name))}</div><div class="member-info"><div class="member-name">${esc(item.name)}</div><div class="muted">${item.balance>0?'Should receive':item.balance<0?'Needs to pay':'Settled up'}</div></div><div class="balance ${item.balance>0?'positive':item.balance<0?'negative':''}">${item.balance>0?'+':item.balance<0?'−':''}${moneySafe(Math.abs(item.balance))}</div></div>`).join(''):'<div class="empty-box">Add members to see balances.</div>';
  const suggestions=balanceResponse.suggested_settlements||[];
  $('settlementSuggestions').innerHTML=suggestions.length?suggestions.map(item=>`<div class="settle-line"><div><strong>${esc(item.from_name)}</strong> pays <strong>${esc(item.to_name)}</strong><div class="muted">Suggested settlement</div></div><div style="text-align:right"><div class="money-large">${moneySafe(item.amount)}</div><button class="btn btn-primary small-button settle-btn" data-from="${item.from_person_id}" data-to="${item.to_person_id}" data-amount="${item.amount}">Record payment</button></div></div>`).join(''):'<div class="empty-box">Everyone is settled up 🎉</div>';
  document.querySelectorAll('.settle-btn').forEach(button=>button.addEventListener('click',()=>recordSettlement(Number(button.dataset.from),Number(button.dataset.to),Number(button.dataset.amount))));
  $('historyCount').textContent=`${activeExpenses.length} records`;
  $('expenseHistory').innerHTML=activeExpenses.length?activeExpenses.map(item=>`<article class="history-card"><div class="history-head"><div><strong>${esc(item.title)}</strong><div class="muted">${esc(item.category)} · ${dateLabel(item.expense_date)} · Paid by ${esc(item.paid_by_name)}</div></div><div class="money-large">${moneySafe(item.total_amount)}</div></div>${item.description?`<p class="muted">${esc(item.description)}</p>`:''}<div class="section-separator"></div><div class="muted" style="font-weight:700;margin-bottom:4px">Shares by member</div>${(item.splits||[]).map(share=>`<div class="preview-line"><span>${esc(share.name)}</span><strong>${moneySafe(share.amount)}</strong></div>`).join('')}</article>`).join(''):'<div class="empty-box">No shared spending recorded yet. Add your first group bill above.</div>';
  $('settlementHistory').innerHTML=settlements.length?settlements.map(item=>`<div class="history-card"><div class="history-head"><div><strong>${esc(item.from_name)}</strong> paid <strong>${esc(item.to_name)}</strong><div class="muted">${dateLabel(item.payment_date)}${item.note?' · '+esc(item.note):''}</div></div><div class="money-large">${moneySafe(item.amount)}</div></div></div>`).join(''):'<div class="empty-box">No payments have been recorded yet.</div>';
}
async function recordSettlement(fromId,toId,amount){
  if(!confirm(`Record ${moneySafe(amount)} paid by ${activeMembers.find(x=>Number(x.person_id)===fromId)?.name||'member'} to ${activeMembers.find(x=>Number(x.person_id)===toId)?.name||'member'}?`))return;
  const note=prompt('Optional payment note:')||'';
  try{await API_CLIENT.post(`/split-groups/${activeGroup.id}/settlements`,{from_person_id:fromId,to_person_id:toId,amount,payment_date:today,note});showToast('Settlement recorded.','success');await refreshGroupData();}
  catch(error){showError(error.message||'Could not record settlement.');}
}
$('createGroupForm').addEventListener('submit',async event=>{
  event.preventDefault();clearError();const name=$('groupName').value.trim();
  try{const group=await API_CLIENT.post('/split-groups',{name,description:$('groupDescription').value.trim()});$('createGroupForm').reset();showToast('Group created. Add your friends by name.','success');await loadGroups(group.id);}
  catch(error){showError(error.message||'Could not create group.');}
});
init();
