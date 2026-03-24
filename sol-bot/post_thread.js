require('dotenv').config();
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path = require('path');
const fs = require('fs');
puppeteer.use(StealthPlugin());

// Parse args: node post_thread.js [--image /path/to/img.jpg] [--video /path/to/vid.mp4] "tweet1" "tweet2" ...
let imagePath = null;
let videoPath = null;
const tweets = [];
const args = process.argv.slice(2);

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--image' && args[i + 1]) {
    imagePath = args[i + 1];
    i++;
  } else if (args[i] === '--video' && args[i + 1]) {
    videoPath = args[i + 1];
    i++;
  } else {
    tweets.push(args[i]);
  }
}

if (tweets.length === 0) {
  console.error('Usage: node post_thread.js [--image path] [--video path] "tweet1" "tweet2" ...');
  process.exit(1);
}

// Video takes priority if both provided
const mediaPath = videoPath || imagePath;
const mediaType = videoPath ? 'video' : (imagePath ? 'image' : null);

async function waitForVideoProcessing(page, timeout = 120000) {
  const startTime = Date.now();
  console.log('Esperando procesamiento de video...');
  let lastLog = 0;

  while (Date.now() - startTime < timeout) {
    try {
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      if (elapsed - lastLog >= 15) {
        console.log('  ...procesando (' + elapsed + 's)');
        lastLog = elapsed;
      }

      const status = await page.evaluate(() => {
        const progressBar = document.querySelector('[role="progressbar"]');
        const processingText = document.body.innerText.includes('Uploading') ||
                               document.body.innerText.includes('Processing');
        const hasMedia = document.querySelector('[data-testid="attachments"]') ||
                         document.querySelector('video') ||
                         document.querySelector('[data-testid="mediaPreview"]');
        const hasError = document.body.innerText.includes('Unable to upload') ||
                         document.body.innerText.includes('try again');
        return {
          processing: progressBar !== null || processingText,
          hasMedia: hasMedia !== null,
          hasError: hasError
        };
      });

      if (status.hasError) {
        console.log('Error detectado durante procesamiento de video');
        return false;
      }

      if (!status.processing && status.hasMedia) {
        console.log('Video procesado OK');
        return true;
      }

      if (!status.processing && !status.hasMedia && elapsed > 10) {
        // No progress bar and no media after 10s - video might have been accepted
        console.log('Video parece listo (sin indicador de progreso)');
        return true;
      }
    } catch (frameErr) {
      // Detached frame error - page reloaded, video likely still processing
      console.log('  Frame recargado, esperando...');
      await new Promise(r => setTimeout(r, 5000));
      continue;
    }

    await new Promise(r => setTimeout(r, 3000));
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    if (elapsed % 15 === 0) console.log(`  ...procesando (${elapsed}s)`);
  }

  console.log('Timeout esperando procesamiento de video');
  return false;
}

async function postThread() {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/usr/bin/google-chrome-stable',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  // Set cookies
  await page.setCookie(
    { name: 'auth_token', value: process.env.X_AUTH_TOKEN, domain: '.x.com' },
    { name: 'ct0', value: process.env.X_CT0, domain: '.x.com' },
    { name: 'twid', value: process.env.X_TWID, domain: '.x.com' }
  );

  let lastTweetId = null;

  for (let i = 0; i < tweets.length; i++) {
    console.log(`Publicando tweet ${i + 1}/${tweets.length}...`);

    if (i === 0) {
      // First: go to home to establish session
      await page.goto('https://x.com/home', { waitUntil: 'networkidle2', timeout: 60000 });
      await new Promise(r => setTimeout(r, 4000));
      // Then navigate to compose
      await page.goto('https://x.com/compose/tweet', { waitUntil: 'networkidle2', timeout: 60000 });
      await new Promise(r => setTimeout(r, 3000));
    } else {
      // Reply to previous tweet
      await page.goto(`https://x.com/napoleotics/status/${lastTweetId}`, { waitUntil: 'networkidle2', timeout: 60000 });
      await new Promise(r => setTimeout(r, 4000));

      // Click reply button
      const replyBtn = await page.waitForSelector('[data-testid="reply"]', { timeout: 10000 });
      await replyBtn.click();
      await new Promise(r => setTimeout(r, 3000));
    }

    // Type tweet text
    const editor = await page.waitForSelector('[data-testid="tweetTextarea_0"]', { timeout: 15000 });
    await editor.click();
    await page.keyboard.type(tweets[i], { delay: 30 + Math.random() * 40 });
    await new Promise(r => setTimeout(r, 2000));

    // Attach media only on first tweet (if provided)
    if (i === 0 && mediaPath && fs.existsSync(mediaPath)) {
      try {
        // X uses the same file input for images AND videos
        const fileInput = await page.$('input[data-testid="fileInput"], input[type="file"]');
        if (fileInput) {
          await fileInput.uploadFile(mediaPath);
          console.log(`${mediaType === 'video' ? 'Video' : 'Imagen'} adjuntado: ${mediaPath}`);

          if (mediaType === 'video') {
            const fileSize = fs.statSync(mediaPath).size;
            const sizeMB = (fileSize / (1024 * 1024)).toFixed(1);
            console.log(`Tamano del video: ${sizeMB} MB`);

            // Wait for upload indicator to appear then disappear
            // Don't use waitForVideoProcessing - it causes detached frame errors
            console.log('Esperando que el video se adjunte...');
            
            // Wait based on file size (roughly 10s per MB + base 15s)
            const waitTime = Math.min(Math.max(15000, sizeMB * 10000 + 15000), 60000);
            console.log(`Esperando ${Math.round(waitTime/1000)}s para upload...`);
            await new Promise(r => setTimeout(r, waitTime));
            
            // Check if publish button is enabled (means video is ready)
            try {
              const btnReady = await page.evaluate(() => {
                const btn = document.querySelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]');
                return btn && !btn.disabled;
              });
              if (btnReady) {
                console.log('Video listo para publicar');
              } else {
                console.log('Esperando 15s mas...');
                await new Promise(r => setTimeout(r, 15000));
              }
            } catch (e) {
              // If evaluate fails, just wait a bit more
              console.log('Esperando 10s adicionales...');
              await new Promise(r => setTimeout(r, 10000));
            }
          } else {
            // Images are fast
            await new Promise(r => setTimeout(r, 5000));
          }
        } else {
          console.log('No se encontro el input de archivo, publicando sin media');
        }
      } catch (mediaErr) {
        if (mediaErr.message.includes('detached Frame')) {
          console.log('Frame se recargo durante upload - video probablemente subido OK');
          await new Promise(r => setTimeout(r, 5000));
        } else {
          console.log(`Error al adjuntar ${mediaType}: ${mediaErr.message}`);
        }
      }
    }

    await new Promise(r => setTimeout(r, 1500));

    // Click publish - with retry for detached frames
    try {
      const btn = await page.waitForSelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]', { timeout: 10000 });
      await btn.click();
    } catch (clickErr) {
      console.log('Reintentando click en publicar...');
      try {
        // Wait for page to stabilize
        await new Promise(r => setTimeout(r, 3000));
        // Try clicking again
        const btn2 = await page.waitForSelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]', { timeout: 15000 });
        await btn2.click();
      } catch (retryErr) {
        console.log('No se pudo hacer click en publicar: ' + retryErr.message);
        // Try keyboard shortcut as last resort
        try {
          await page.keyboard.down('Control');
          await page.keyboard.press('Enter');
          await page.keyboard.up('Control');
          console.log('Publicado con Ctrl+Enter');
        } catch (kbErr) {
          console.log('Fallo total al publicar: ' + kbErr.message);
        }
      }
    }

    // Videos need more time after clicking publish (X may still be uploading)
    const postWait = (i === 0 && mediaType === 'video') ? 15000 : 5000;
    await new Promise(r => setTimeout(r, postWait));

    // Capture tweet ID
    const currentUrl = page.url();
    const match = currentUrl.match(/status\/(\d+)/);
    if (match) {
      lastTweetId = match[1];
    } else {
      // Go to profile and find latest tweet
      await page.goto('https://x.com/napoleotics', { waitUntil: 'networkidle2', timeout: 20000 });
      await new Promise(r => setTimeout(r, 3000));
      const links = await page.$$eval('a[href*="/napoleotics/status/"]', els =>
        els.map(el => el.href).filter(h => h.match(/\/status\/\d+$/))
      );
      if (links.length > 0) {
        const m = links[0].match(/status\/(\d+)/);
        if (m) lastTweetId = m[1];
      }
    }

    console.log(`Tweet ${i + 1} publicado. ID: ${lastTweetId}`);

    // Random delay between tweets (8-15 seconds)
    if (i < tweets.length - 1) {
      const delay = 8000 + Math.floor(Math.random() * 7000);
      console.log(`Esperando ${Math.round(delay/1000)}s...`);
      await new Promise(r => setTimeout(r, delay));
    }
  }

  await browser.close();
  console.log(`Listo: ${tweets.length} tweet(s) publicados.`);
}

postThread().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
