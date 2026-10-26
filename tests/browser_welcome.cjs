'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../.test-tools/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'android/app/src/main/assets/welcome');
const version = fs.readFileSync(path.join(root,'android_agent/__init__.py'),'utf8').split(String.fromCharCode(10)).find(l=>l.startsWith('__version__')).split('"')[1];
const renderer = fs.readFileSync(path.join(assets,'lottie.min.js'),'utf8');
const animationData = fs.readFileSync(path.join(assets,'eZ.json'),'utf8');
const html = fs.readFileSync(path.join(assets,'eZ.html'),'utf8')
  .replace('<script src="lottie.min.js"></script>', () => '<script>' + renderer + '</script>')
  .replace("path: 'eZ.json',", () => 'animationData: ' + animationData + ',');
(async () => {
  const browser = await chromium.launch({executablePath: process.env.BROWSER_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true});
  const page = await browser.newPage({viewport:{width:334,height:400}});
  const errors=[]; const requests=[]; const checks=[]; const pixels=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>requests.push(r.url()));
  const state=()=>page.evaluate(()=>{const a=lottie.getRegisteredAnimations()[0];return {loaded:a.isLoaded,paused:a.isPaused,frame:a.currentFrame,total:a.totalFrames};});
  const visiblePixels=()=>page.evaluate(()=>{
    const c=document.querySelector('canvas');
    const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let count=0;
    for(let i=0;i<d.length;i+=4) if(d[i+3]>10 && Math.min(d[i],d[i+1],d[i+2])<220) count++;
    return count;
  });
  try {
    await page.setContent(html,{waitUntil:'load'});
    await page.waitForFunction(()=>window.setWelcomeMotion && lottie.getRegisteredAnimations()[0]?.isLoaded);
    assert.equal((await state()).total,1126);checks.push('supplied eZ composition and embedded bitmap assets load locally');
    assert.equal((await state()).paused,true);assert((await visiblePixels())>1000);checks.push('initial reduced-motion frame contains visible artwork');
    const paused=(await state()).frame;
    await page.evaluate(()=>window.setWelcomeMotion(true));
    await page.waitForFunction(start=>lottie.getRegisteredAnimations()[0].currentFrame>start+3,paused);
    assert.equal((await state()).paused,false);checks.push('play command advances actual Lottie frames');
    await page.evaluate(()=>window.setWelcomeMotion(false));
    assert.equal((await state()).paused,true);checks.push('pause command stops playback with visible artwork');
    // Later precompositions must draw pixels, not merely advance currentFrame.
    for(const frame of [180,315,390,450,600,900,1035,1100,1125]) {
      await page.evaluate(f=>lottie.getRegisteredAnimations()[0].goToAndStop(f,true),frame);
      const count=await visiblePixels();pixels.push({frame,darkPixels:count});
      assert(count>600,'frame '+frame+' lost its artwork: only '+count+' visible pixels');
      checks.push('visible artwork at frame '+frame+' ('+count+' pixels)');
      if([600,1100].includes(frame)) await page.screenshot({path:path.join(root,'artifacts','welcome-frame'+frame+'-v'+version+'.png')});
    }
    await page.evaluate(()=>lottie.getRegisteredAnimations()[0].goToAndStop(600,true));
    await page.evaluate(()=>window.setWelcomeMotion(false));
    assert.equal((await state()).frame,600);checks.push('lifecycle pause preserves the current frame');
    await page.evaluate(()=>window.setWelcomeMotion(false,true));
    assert.equal((await state()).frame,315);checks.push('reduced motion uses a visible static frame');
    await page.evaluate(()=>lottie.getRegisteredAnimations()[0].goToAndStop(580,true));
    await page.evaluate(()=>window.setWelcomeMotion(true));
    await page.waitForFunction(()=>lottie.getRegisteredAnimations()[0].currentFrame>620);
    assert((await visiblePixels())>600);checks.push('late precomposition remains visible during continuous playback');
    await page.evaluate(()=>lottie.getRegisteredAnimations()[0].goToAndStop(1120,true));
    await page.evaluate(()=>window.setWelcomeMotion(true));
    await page.waitForFunction(()=>lottie.getRegisteredAnimations()[0].currentFrame<60);
    assert((await visiblePixels())>100);checks.push('end of composition loops to visible first frames');
    await page.evaluate(()=>window.setWelcomeMotion(false));
    await page.evaluate(()=>window.setWelcomeMotion(false,true));
    await page.setViewportSize({width:280,height:180});
    await page.waitForFunction(()=>document.querySelector('canvas').width===280);
    assert((await visiblePixels())>250);checks.push('artwork remains visible after compact viewport resize');
    await page.setViewportSize({width:334,height:270});
    await page.waitForFunction(()=>document.querySelector('canvas').width===334);
    await page.screenshot({path:path.join(root,'artifacts','welcome-art-v'+version+'.png')});
    assert.deepEqual(requests,[]);checks.push('inline renderer makes no external requests');
    assert.deepEqual(errors,[]);checks.push('no uncaught renderer errors');
    const lines=checks.map((c,i)=>'PASS '+(i+1)+' '+c);
    lines.push(checks.length+'/'+checks.length+'; pageErrors='+JSON.stringify(errors)+'; requests='+JSON.stringify(requests));
    lines.push('Timeline pixels: '+JSON.stringify(pixels));
    const report=lines.join(String.fromCharCode(10))+String.fromCharCode(10);
    fs.writeFileSync(path.join(root,'artifacts','browser-v'+version+'-welcome.txt'),report,'utf8');
    console.log(report);
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
