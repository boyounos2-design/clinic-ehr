"use strict";
/* Paper-sheet intake + admin settings. Loaded BEFORE the main script; everything here runs lazily (on click),
   using S, t, api, esc, $, toast, nav, isClin, isDoc, nn from the main script. */
const IT={en:{intake:"Import from sheet",title:"Import a patient from a paper sheet",hint:"Upload a photo or scan of the patient's sheet. The details are read and filled in for you — you review them, then save.",
 pick:"Choose photo or PDF",cam:"Take a photo",or:"or drop the file here",reading:"Reading the sheet…",readingSub:"This can take up to a minute.",
 engine:"Reading method",auto:"Automatic",local:"On this PC",ai:"AI (Claude)",ocrspace:"OCR.Space (online)",ocrspaceOn:"OCR.Space is set up",usedOcrspace:"Read by OCR.Space (online OCR). The sheet image was sent to the OCR.Space service. Check every field.",aiOn:"AI reading is available",aiOff:"No online reader is set up — printed text only, read on this PC.",setupAi:"Set up",
 ocrOff:"Text reader (Tesseract) is not installed on this PC — images cannot be read yet. See the instructions.",
 usedAi:"Read by AI (Claude). The sheet image was sent to Anthropic's service for reading.",usedLocal:"Read on this PC — the image did not leave your computer. Handwriting may be read poorly.",usedNone:"The sheet could not be read automatically.",
 review:"Check every field before saving. Fields marked “Check” were not read with confidence.",check:"Check",
 dup:"This patient may already exist:",openExisting:"Open",saveNew:"Save as new patient",
 secPatient:"Patient",secHistory:"Past history",secVisit:"Today's visit",secFollow:"Follow-up",
 name:"Full name",age:"Age (years)",dob:"Date of birth",gender:"Gender",phone:"Phone",address:"Address",
 male:"Male",female:"Female",other:"Other",unknown:"Unknown",
 history:"Past history",complaint:"Chief complaint",symptoms:"Symptoms",exam:"Physical examination",dx:"Diagnosis",plan:"Management plan",notes:"Other notes",
 fuDate:"Follow-up date",fuReason:"Reason",raw:"Text read from the sheet",back:"Choose another sheet",save:"Save patient",cancel:"Cancel",
 roleNote:"Your account saves the patient's details only; clinical sections are entered by the doctor.",skipped:"Saved. Not saved for your role:",
 dupConfirm:"A patient with the same name or phone already exists:\n\n",dupAsk:"\n\nSave as a NEW patient anyway?",attached:"The sheet image was attached to the patient's documents.",
 settings:"Settings",osTitle:"OCR.Space (trial reader)",osKey:"OCR.Space API key",osKeyHelp:"Free key from ocr.space. Reads printed and handwritten text. Leave empty and save to switch it off.",osPrivacy:"Privacy: with OCR.Space ON, the photo of each sheet is sent to OCR.Space. Use it for TESTING with sample sheets, not real patient data, until you have checked their terms.",aiTitle:"AI sheet reading (Claude)",aiState:"Status",aiEnabled:"Enabled",aiDisabled:"Not enabled",aiKey:"Anthropic API key",aiKeyHelp:"Paste your key to enable AI reading of handwritten sheets. Sheet images are then sent to Anthropic for reading. Leave empty and save to switch it off.",
 aiPrivacy:"Privacy: with AI reading ON, the photo of each sheet leaves this PC. Make sure that is acceptable for your patients' data.",saved:"Saved",failed:"Something went wrong"},
ar:{intake:"استيراد من ورقة",title:"استيراد مريض من ورقة",hint:"ارفع صورة أو مسحًا ضوئيًا لورقة المريض. تُقرأ البيانات وتُعبّأ تلقائيًا — وأنت تراجعها ثم تحفظ.",
 pick:"اختيار صورة أو ملف PDF",cam:"تصوير بالكاميرا",or:"أو اسحب الملف إلى هنا",reading:"جارٍ قراءة الورقة…",readingSub:"قد يستغرق حتى دقيقة.",
 engine:"طريقة القراءة",auto:"تلقائي",local:"على هذا الجهاز",ai:"ذكاء اصطناعي (Claude)",ocrspace:"OCR.Space (أونلاين)",ocrspaceOn:"OCR.Space مفعّل",usedOcrspace:"قُرئت بواسطة OCR.Space (قراءة نصوص أونلاين). أُرسلت صورة الورقة إلى خدمة OCR.Space. راجع كل خانة.",aiOn:"القراءة بالذكاء الاصطناعي متاحة",aiOff:"لا توجد قراءة أونلاين مفعّلة — النص المطبوع فقط، يُقرأ على هذا الجهاز.",setupAi:"تفعيل",
 ocrOff:"برنامج قراءة النص (Tesseract) غير مثبّت على هذا الجهاز — لا يمكن قراءة الصور بعد. راجع التعليمات.",
 usedAi:"قرأها الذكاء الاصطناعي (Claude). أُرسلت صورة الورقة إلى خدمة Anthropic لقراءتها.",usedLocal:"قُرئت على هذا الجهاز — لم تغادر الصورة جهازك. قد يُقرأ الخط اليدوي بشكل ضعيف.",usedNone:"تعذّرت قراءة الورقة تلقائيًا.",
 review:"راجع كل خانة قبل الحفظ. الخانات المعلَّمة «راجع» لم تُقرأ بثقة.",check:"راجع",
 dup:"قد يكون هذا المريض موجودًا بالفعل:",openExisting:"فتح",saveNew:"حفظ كمريض جديد",
 secPatient:"بيانات المريض",secHistory:"التاريخ المرضي",secVisit:"زيارة اليوم",secFollow:"المتابعة",
 name:"الاسم الكامل",age:"السن (بالسنوات)",dob:"تاريخ الميلاد",gender:"النوع",phone:"الهاتف",address:"العنوان",
 male:"ذكر",female:"أنثى",other:"آخر",unknown:"غير محدد",
 history:"التاريخ المرضي",complaint:"الشكوى الرئيسية",symptoms:"الأعراض",exam:"الفحص الإكلينيكي",dx:"التشخيص",plan:"خطة العلاج",notes:"ملاحظات أخرى",
 fuDate:"موعد المتابعة",fuReason:"السبب",raw:"النص المقروء من الورقة",back:"اختيار ورقة أخرى",save:"حفظ المريض",cancel:"إلغاء",
 roleNote:"حسابك يحفظ بيانات المريض فقط؛ الأقسام السريرية يدخلها الطبيب.",skipped:"تم الحفظ. لم يُحفظ لصلاحيتك:",
 dupConfirm:"يوجد مريض بنفس الاسم أو الهاتف:\n\n",dupAsk:"\n\nهل تريد الحفظ كمريض جديد على أي حال؟",attached:"أُرفقت صورة الورقة بمستندات المريض.",
 settings:"الإعدادات",osTitle:"OCR.Space (قارئ التجربة)",osKey:"مفتاح OCR.Space",osKeyHelp:"مفتاح مجاني من ocr.space. يقرأ المطبوع والمكتوب بخط اليد. اتركه فارغًا واحفظ لإيقافه.",osPrivacy:"الخصوصية: عند تفعيل OCR.Space تُرسل صورة كل ورقة إليه. استخدمه للتجربة بأوراق وهمية وليس ببيانات مرضى حقيقيين قبل مراجعة شروطه.",aiTitle:"قراءة الورق بالذكاء الاصطناعي (Claude)",aiState:"الحالة",aiEnabled:"مفعّلة",aiDisabled:"غير مفعّلة",aiKey:"مفتاح Anthropic API",aiKeyHelp:"الصق المفتاح لتفعيل قراءة الورق المكتوب بخط اليد. عندها تُرسل صور الأوراق إلى Anthropic لقراءتها. اتركه فارغًا واحفظ لإيقافها.",
 aiPrivacy:"الخصوصية: عند تفعيل الذكاء الاصطناعي تغادر صورة كل ورقة هذا الجهاز. تأكد أن هذا مقبول لبيانات مرضاك.",saved:"تم الحفظ",failed:"حدث خطأ"}};
IT.en.account="Account";IT.en.myPw="Change my password";IT.en.oldPw="Current password";IT.en.newPw="New password (8+ characters)";IT.en.users="Users";IT.en.addUser="Add user";IT.en.username="Username";IT.en.fullName="Full name";IT.en.role="Role";IT.en.pwDone="Password changed";IT.en.userAdded="User added";IT.en.close="Close";
IT.en.r_doctor="Doctor";IT.en.r_nurse="Nurse";IT.en.r_receptionist="Receptionist";IT.en.r_admin="Admin";
IT.ar.account="حسابي";IT.ar.myPw="تغيير كلمة السر";IT.ar.oldPw="كلمة السر الحالية";IT.ar.newPw="كلمة السر الجديدة (8 أحرف فأكثر)";IT.ar.users="المستخدمون";IT.ar.addUser="إضافة مستخدم";IT.ar.username="اسم المستخدم";IT.ar.fullName="الاسم الكامل";IT.ar.role="الدور";IT.ar.pwDone="تم تغيير كلمة السر";IT.ar.userAdded="تمت إضافة المستخدم";IT.ar.close="إغلاق";
IT.ar.r_doctor="طبيب";IT.ar.r_nurse="تمريض";IT.ar.r_receptionist="سكرتارية";IT.ar.r_admin="مدير النظام";
const it=k=>(IT[S.lang]&&IT[S.lang][k])??IT.en[k]??k;
const ICON_SHEET='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/></svg>';
const IN={mode:"auto",st:{ai:false,ocr:false},file:null,url:null};

function inShell(html){const d=$("#dlg");d.className="wide";d.innerHTML=`<div class="dlg-in"><div class="row sp"><h2 style="margin:0">${esc(it("title"))}</h2><button type="button" class="btn sm" data-a="close">${esc(it("cancel"))}</button></div>${html}</div>`;if(!d.open)d.showModal()}

async function openIntake(){
 IN.st=await api("/intake/status").catch(()=>({ai:false,ocr:false}));IN.mode="auto";stepUpload()}

function stepUpload(){
 const st=IN.st;
 inShell(`<p class="mute" style="margin:10px 0 18px">${esc(it("hint"))}</p>
 <div class="drop big" id="indrop" tabindex="0" role="button"><div class="dropicon">${ICON_SHEET}</div><b>${esc(it("pick"))}</b><div class="mute small">${esc(it("or"))}</div></div>
 <input type="file" id="infile" accept="image/*,application/pdf" hidden><input type="file" id="incam" accept="image/*" capture="environment" hidden>
 <div class="row" style="margin-top:14px"><button type="button" class="btn" id="incambtn">${esc(it("cam"))}</button>
 ${(st.ai||st.ocrspace)?`<span class="mute">${esc(it("engine"))}:</span><div class="chips" role="group">${["auto","local",...(st.ocrspace?["ocrspace"]:[]),...(st.ai?["ai"]:[])].map(m=>`<button type="button" class="chip" data-mode="${m}" aria-pressed="${IN.mode===m}">${esc(it(m))}</button>`).join("")}</div>`:""}</div>
 <p class="note ${(st.ai||st.ocrspace)?"ok":""}" style="margin-top:16px">${esc(st.ai?it("aiOn"):st.ocrspace?it("ocrspaceOn"):it("aiOff"))} ${S.user.role==="admin"&&!st.ai&&!st.ocrspace?`<button type="button" class="btn sm" id="insetup">${esc(it("setupAi"))}</button>`:""}</p>
 ${!st.ocr&&!st.ai&&!st.ocrspace?`<p class="note warn">${esc(it("ocrOff"))}</p>`:""}`);
 const drop=$("#indrop"),fi=$("#infile"),cam=$("#incam");
 drop.onclick=()=>fi.click();drop.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fi.click()}};
 drop.ondragover=e=>{e.preventDefault();drop.classList.add("over")};drop.ondragleave=()=>drop.classList.remove("over");
 drop.ondrop=e=>{e.preventDefault();drop.classList.remove("over");if(e.dataTransfer.files[0])extract(e.dataTransfer.files[0])};
 fi.onchange=()=>fi.files[0]&&extract(fi.files[0]);cam.onchange=()=>cam.files[0]&&extract(cam.files[0]);$("#incambtn").onclick=()=>cam.click();
 document.querySelectorAll("[data-mode]").forEach(b=>b.onclick=()=>{IN.mode=b.dataset.mode;stepUpload()});
 const su=$("#insetup");if(su)su.onclick=openSettings}

/* Vercel limits request bodies to 4.5MB: shrink big photos in the browser before sending. */
async function shrinkImg(f,max=3.5e6){
 if(!f||!f.type||!f.type.startsWith("image/")||f.size<=max)return f;
 try{const bm=await createImageBitmap(f);let sc=Math.min(1,2600/Math.max(bm.width,bm.height)),q=.85,b;
  for(let i=0;i<6;i++){const c=document.createElement("canvas");c.width=Math.round(bm.width*sc);c.height=Math.round(bm.height*sc);
   c.getContext("2d").drawImage(bm,0,0,c.width,c.height);b=await new Promise(r=>c.toBlob(r,"image/jpeg",q));
   if(b&&b.size<=max)break;sc*=.8;q=Math.max(.6,q-.05)}
  return b?new File([b],f.name.replace(/\.\w+$/,"")+".jpg",{type:"image/jpeg"}):f}catch(e){return f}}

async function extract(file){
 file=await shrinkImg(file);
 IN.file=file;if(IN.url)URL.revokeObjectURL(IN.url);IN.url=URL.createObjectURL(file);
 inShell(`<div class="loading"><div class="spin"></div><b>${esc(it("reading"))}</b><div class="mute">${esc(it("readingSub"))}</div></div>`);
 const fd=new FormData();fd.append("file",file);fd.append("mode",IN.mode);
 try{const r=await api("/intake/extract",{method:"POST",form:fd});stepReview(r)}
 catch(e){if(e.message==="auth")return;stepUpload();const p=document.createElement("p");p.className="pill bad";p.setAttribute("role","alert");p.textContent=e.message;$("#dlg .dlg-in").appendChild(p)}}

function rf(name,label,v,conf,type="text",extra=""){ // review field: low-confidence values get a visible "Check" flag
 const low=conf&&conf[name]==="low",val=esc(v??"");
 const ctl=type==="textarea"?`<textarea id="r_${name}" name="${name}" rows="2" ${extra}>${val}</textarea>`:
  type==="gender"?`<select id="r_${name}" name="${name}">${["male","female","other","unknown"].map(o=>`<option value="${o}" ${o===(v||"unknown")?"selected":""}>${esc(it(o))}</option>`).join("")}</select>`:
  `<input id="r_${name}" name="${name}" type="${type}" value="${val}" ${extra}>`;
 return `<div class="fld${low?" review":""}"><label for="r_${name}">${esc(label)}${low?` <span class="flag">${esc(it("check"))}</span>`:""}</label>${ctl}</div>`}

function stepReview(r,force=false){
 const f=r.fields,c=r.confidence||{},doc=isDoc(),clin=isClin();
 const eng=r.engine==="ai"?["info",it("usedAi")]:r.engine==="ocrspace"?["info",it("usedOcrspace")]:r.engine==="local"?["info",it("usedLocal")]:["warn",it("usedNone")];
 const isPdf=r.mime==="application/pdf";
 const dups=(r.duplicates||[]).length?`<div class="note warn"><b>${esc(it("dup"))}</b>${r.duplicates.map(d=>`<div class="row sp" style="margin-top:8px"><span>${esc(d.full_name)} <bdi class="mute">#${d.mrn} ${esc(d.phone||"")}</bdi></span><button type="button" class="btn sm" data-a="openP" data-id="${d.id}">${esc(it("openExisting"))}</button></div>`).join("")}</div>`:"";
 inShell(`<form id="inform" class="review-grid">
  <div class="preview">${isPdf?`<iframe src="${IN.url}" title="sheet"></iframe>`:`<img src="${IN.url}" alt="sheet">`}<button type="button" class="btn sm" id="inback" style="margin-top:10px">${esc(it("back"))}</button></div>
  <div class="fields">
   <p class="note ${eng[0]}">${esc(eng[1])}</p>${(r.warnings||[]).map(w=>`<p class="note warn">${esc(w)}</p>`).join("")}${dups}
   <p class="mute small" style="margin:6px 0 0">${esc(it("review"))}</p>
   <h3>${esc(it("secPatient"))}</h3>
   ${rf("full_name",it("name"),f.full_name,c,"text","required minlength=2")}
   <div class="field-pair">${rf("age",it("age"),f.age,c,"number",'min="0" max="120"')}${rf("dob",it("dob"),f.dob,c,"date")}</div>
   <div class="field-pair">${rf("gender",it("gender"),f.gender,c,"gender")}${rf("phone",it("phone"),f.phone,c,"tel")}</div>
   ${rf("address",it("address"),f.address,c)}
   ${clin?`<h3>${esc(it("secHistory"))}</h3>${rf("past_history",it("history"),f.past_history,c,"textarea")}`:""}
   ${doc?`<h3>${esc(it("secVisit"))}</h3>${rf("chief_complaint",it("complaint"),f.chief_complaint,c,"textarea")}${rf("symptoms",it("symptoms"),f.symptoms,c,"textarea")}${rf("examination",it("exam"),f.examination,c,"textarea")}
    <div class="field-pair">${rf("diagnosis",it("dx"),f.diagnosis,c)}<div></div></div>${rf("management_plan",it("plan"),f.management_plan,c,"textarea")}${rf("physician_notes",it("notes"),f.physician_notes,c,"textarea")}
    <h3>${esc(it("secFollow"))}</h3><div class="field-pair">${rf("follow_up",it("fuDate"),f.follow_up,c,"date")}${rf("follow_up_reason",it("fuReason"),f.follow_up_reason,c)}</div>`:`<p class="note">${esc(it("roleNote"))}</p>`}
   ${r.raw_text?`<details style="margin-top:14px"><summary>${esc(it("raw"))}</summary><pre class="ocr">${esc(r.raw_text)}</pre></details>`:""}
   <p id="inerr" class="pill bad" role="alert" style="display:none"></p>
   <div class="row sp savebar"><button type="button" class="btn" data-a="close">${esc(it("cancel"))}</button><button class="btn primary" id="insave">${esc(it("save"))}</button></div>
  </div></form>`);
 $("#inback").onclick=stepUpload;
 $("#inform").onsubmit=async e=>{e.preventDefault();const v=Object.fromEntries(new FormData(e.target)),n=x=>(x===undefined||x===""?null:x);
  const body={intake_id:r.intake_id,force,patient:{full_name:v.full_name.trim(),date_of_birth:n(v.dob),age_years:v.dob?null:(v.age?+v.age:null),phone:n(v.phone),address:n(v.address),gender:v.gender||"unknown"},
   past_history:n(v.past_history),chief_complaint:n(v.chief_complaint),symptoms:n(v.symptoms),examination:n(v.examination),diagnosis:n(v.diagnosis),
   management_plan:n(v.management_plan),physician_notes:n(v.physician_notes),follow_up_date:n(v.follow_up),follow_up_reason:n(v.follow_up_reason)};
  const btn=$("#insave");btn.disabled=true;
  try{const out=await api("/intake/commit",{method:"POST",body});$("#dlg").close();toast(it("saved")+(out.sheet_attached?" · "+it("attached"):"")+(out.skipped.length?" · "+it("skipped")+" "+out.skipped.join(", "):""));nav("patient",{pid:out.patient.id,ptab:"overview"})}
  catch(er){btn.disabled=false;if(er.data&&er.data.duplicates){if(confirm(it("dupConfirm")+er.data.duplicates.map(d=>`• ${d.full_name} #${d.mrn} ${d.phone||""}`).join("\n")+it("dupAsk"))){const b2=Object.assign({},body,{force:true});
     try{const out=await api("/intake/commit",{method:"POST",body:b2});$("#dlg").close();toast(it("saved"));nav("patient",{pid:out.patient.id,ptab:"overview"})}catch(e2){showErr(e2.message)}}}
   else if(er.message!=="auth")showErr(er.message)}};
 function showErr(m){const x=$("#inerr");x.textContent=m;x.style.display="inline-block"}}

async function openSettings(){
 const st=await api("/settings").catch(()=>null);if(!st)return;const d=$("#dlg");d.className="";
 d.innerHTML=`<form id="setf" style="padding:24px"><h2 style="margin-top:0">${esc(it("settings"))}</h2>
  <h3>${esc(it("osTitle"))}</h3><p>${esc(it("aiState"))}: <span class="pill ${st.ocrspace?"ok":""}">${esc(st.ocrspace?it("aiEnabled"):it("aiDisabled"))}</span></p>${st.ocrspace_from_env?"":`<label for="oskey">${esc(it("osKey"))}</label><input id="oskey" type="password" autocomplete="off" dir="ltr"><p class="mute small">${esc(it("osKeyHelp"))}</p>`}<p class="note warn">${esc(it("osPrivacy"))}</p><h3>${esc(it("aiTitle"))}</h3><p>${esc(it("aiState"))}: <span class="pill ${st.ai?"ok":""}">${esc(st.ai?it("aiEnabled"):it("aiDisabled"))}</span></p>${st.ai_from_env?"":`<label for="aikey">${esc(it("aiKey"))}</label><input id="aikey" type="password" autocomplete="off" placeholder="sk-ant-…" dir="ltr"><p class="mute small">${esc(it("aiKeyHelp"))}</p>`}
  <p class="note warn">${esc(it("aiPrivacy"))}</p><p id="seterr" class="pill bad" role="alert" style="display:none"></p>
  <div class="row sp" style="margin-top:18px"><button type="button" class="btn" data-a="close">${esc(it("cancel"))}</button>${st.ai_from_env&&st.ocrspace_from_env?"":`<button class="btn primary">${esc(it("save"))}</button>`}</div></form>`;
 d.showModal();$("#setf").onsubmit=async e=>{e.preventDefault();try{if($("#oskey"))await api("/settings/ocrspace-key",{method:"POST",body:{key:$("#oskey").value||""}});if($("#aikey"))await api("/settings/ai-key",{method:"POST",body:{key:$("#aikey").value||""}});d.close();toast(it("saved"))}catch(er){const x=$("#seterr");x.textContent=er.message;x.style.display="inline-block"}}}


async function openAccount(){
 const adm=S.user.role==="admin";let list=[];if(adm)list=await api("/users").catch(()=>[]);
 const d=$("#dlg");d.className="";
 d.innerHTML=`<div class="dlg-in"><div class="row sp"><h2 style="margin:0">${esc(it("account"))} — ${esc(S.user.full_name||S.user.username||"")}</h2><button type="button" class="btn sm" data-a="close">${esc(it("close"))}</button></div>
 <form id="pwf"><h3>${esc(it("myPw"))}</h3><label for="pw_o">${esc(it("oldPw"))}</label><input id="pw_o" type="password" autocomplete="current-password" required>
 <label for="pw_n">${esc(it("newPw"))}</label><input id="pw_n" type="password" autocomplete="new-password" minlength="8" required><p id="pwerr" class="pill bad" role="alert" style="display:none"></p>
 <div class="row" style="margin-top:14px"><button class="btn primary">${esc(t("save"))}</button></div></form>
 ${adm?`<hr style="border:0;border-top:1px solid var(--line);margin:24px 0"><h3>${esc(it("users"))}</h3>
 ${list.map(x=>`<div class="item row sp"><span><b>${esc(x.full_name)}</b> <bdi class="mute">${esc(x.username)}</bdi></span><span class="pill">${esc(it("r_"+x.role))}</span></div>`).join("")}
 <form id="uf" style="margin-top:12px"><h3>${esc(it("addUser"))}</h3><div class="field-pair"><div><label for="u_n">${esc(it("username"))}</label><input id="u_n" required minlength="3" autocomplete="off" dir="ltr"></div><div><label for="u_f">${esc(it("fullName"))}</label><input id="u_f" required></div>
 <div><label for="u_p">${esc(it("newPw"))}</label><input id="u_p" type="password" minlength="8" required autocomplete="new-password"></div><div><label for="u_r">${esc(it("role"))}</label><select id="u_r">${["doctor","nurse","receptionist","admin"].map(r=>`<option value="${r}">${esc(it("r_"+r))}</option>`).join("")}</select></div></div>
 <p id="uerr" class="pill bad" role="alert" style="display:none"></p><div class="row" style="margin-top:14px"><button class="btn primary">${esc(it("addUser"))}</button></div></form>`:""}</div>`;
 d.showModal();
 $("#pwf").onsubmit=async e=>{e.preventDefault();try{await api("/auth/change-password",{method:"POST",body:{old_password:$("#pw_o").value,new_password:$("#pw_n").value}});d.close();toast(it("pwDone"))}catch(er){if(er.message==="auth")return;const x=$("#pwerr");x.textContent=er.message;x.style.display="inline-block"}};
 const uf=$("#uf");if(uf)uf.onsubmit=async e=>{e.preventDefault();try{await api("/users",{method:"POST",body:{username:$("#u_n").value.trim(),password:$("#u_p").value,full_name:$("#u_f").value.trim(),role:$("#u_r").value}});toast(it("userAdded"));openAccount()}catch(er){const x=$("#uerr");x.textContent=er.message;x.style.display="inline-block"}}}
