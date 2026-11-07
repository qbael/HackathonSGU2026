const fs=require('fs');
const {chromium}=require('/home/bael/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 fs.mkdirSync('.cache/docs/erd',{recursive:true});
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const page=await browser.newPage();
 page.on('pageerror',e=>console.log('pageerror',e.message));
 await page.setContent('<!doctype html><html><head><style>body{margin:0;background:white}#graph{position:relative;overflow:hidden;background:white}</style></head><body><div id="graph"></div></body></html>');
 await page.evaluate(()=>{window.mxLoadResources=false;window.mxLoadStylesheets=false;});
 await page.addScriptTag({path:'scripts/docs/erd/drawio-mxClient.js'});
 await page.addScriptTag({path:'scripts/docs/erd/mxER.js'});
 await page.evaluate(()=>{mxCodec.allowlist=['mxStylesheet','Array','mxGraphModel','mxCell','mxGeometry','mxRectangle','mxPoint'];});
 const xml=fs.readFileSync('docs/database/findie-erd.drawio','utf8');
 const pages=await page.evaluate(xml=>Array.from(new DOMParser().parseFromString(xml,'text/xml').querySelectorAll('diagram')).map(p=>({id:p.getAttribute('id'),name:p.getAttribute('name'),width:Number(p.querySelector('mxGraphModel').getAttribute('pageWidth')),height:Number(p.querySelector('mxGraphModel').getAttribute('pageHeight'))})),xml);
 let report=[];
 for(const [i,p] of pages.entries()){
  await page.setViewportSize({width:p.width,height:p.height});
  const r=await page.evaluate(({xml,id,width,height})=>{
   if(window.graph && typeof window.graph.destroy === "function")window.graph.destroy();
   const c=document.getElementById('graph');c.replaceChildren();c.style.width=width+'px';c.style.height=height+'px';
   const g=window.graph=new mxGraph(c);g.setEnabled(false);g.setHtmlLabels(true);
   g.getStylesheet().putCellStyle('text',{shape:'rectangle',strokeColor:'none',fillColor:'none'});
   const doc=mxUtils.parseXml(xml);const model=Array.from(doc.getElementsByTagName('diagram')).find(n=>n.getAttribute('id')===id).getElementsByTagName('mxGraphModel')[0];
   const isolated=mxUtils.parseXml(mxUtils.getXml(model));const codec=new mxCodec(isolated);codec.decode(isolated.documentElement,g.getModel());g.refresh();g.view.validate();
   const overflow=[];for(const key of Object.keys(g.getModel().cells)){
    const cell=g.getModel().cells[key],s=g.view.getState(cell);if(!s?.text?.boundingBox||!cell.vertex)continue;
    const b=s.text.boundingBox;if(b.height>s.height+6)overflow.push({id:key,text:g.convertValueToString(cell).slice(0,100),textHeight:b.height,cellHeight:s.height});
   }
   return {xmlModel:model.nodeName, xmlCells:model.querySelectorAll('mxCell').length, registered:Object.keys(mxCodecRegistry.codecs).slice(0,10), codec:mxCodecRegistry.getCodec('mxGraphModel')?.constructor?.name, root:g.model.root?.children?.length, cellKeys:Object.keys(g.model.cells).slice(0,10), vertices:Object.values(g.model.cells).filter(c=>c.vertex).length,edges:Object.values(g.model.cells).filter(c=>c.edge).length,overflow};
  },{xml,...p});
  await page.screenshot({path:`.cache/docs/erd/page-${i+1}.png`});
  report.push({...p,...r});console.log(JSON.stringify(report.at(-1)));
 }
 fs.copyFileSync('.cache/docs/erd/page-1.png','docs/assets/findie-erd-overview.png');
 fs.writeFileSync('.cache/docs/erd/render-check.json',JSON.stringify(report,null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
