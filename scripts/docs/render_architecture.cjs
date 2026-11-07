const {chromium}=require('/home/bael/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 const p=await b.newPage({viewport:{width:1800,height:870},deviceScaleFactor:1});
 await p.goto(pathToFileURL(path.resolve('docs/assets/kien-truc-he-thong.svg')).href);
 await p.screenshot({path:'docs/assets/kien-truc-he-thong.png'});
 await b.close();
})();
