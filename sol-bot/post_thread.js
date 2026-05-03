require('dotenv').config();
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path = require('path');
const fs = require('fs');
puppeteer.use(StealthPlugin());

// Parse args: node post_thread.js [--image img1.jpg] [--image img2.jpg] [--video vid.mp4] "tweet1" "tweet2" ...
const imagePaths = [];
let videoPath = null;
const tweets = [];
const args = process.argv.slice(2);

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--image' && args[i + 1]) {
    imagePaths.push(args[i + 1]);
    i++;
  } else if (args[i] === '--images' && args[i + 1]) {
    // Comma-separated: --images img1.jpg,img2.jpg
    args[i + 1].split(',').forEach(p => p.trim() && imagePaths.push(p.trim()));
    i++;
  } else if (args[i] === '--video' && args[i + 1]) {
    videoPath = args[i + 1];
    i++;
  } else {
    tweets.push(args[i]);
  }
}

if (tweets.length === 0) {
  console.error('Usage: node post_thread.js [--image path] [--images p1,p2] [--video path] "tweet1" "tweet2" ...');
  process.exit(1);
}

// Validate media files exist upfront
if (videoPath && !fs.existsSync(videoPath)) {
  console.log('[WARN] Video file not found: ' + videoPath + ' — publishing without media');
  videoPath = null;
}
const validImages = imagePaths.filter(p => {
  const ok = fs.existsSync(p);
  if (!ok) console.log('[WARN] Image file not found: ' + p + ' — skipping');
  return ok;
});

const mediaType = videoPath ? 'video' : (validImages.length > 0 ? 'image' : null);
const mediaPath = videoPath || (validImages.length > 0 ? validImages[0] : null);

async function postThread() {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/usr/bin/google-chrome-stable',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });

  const page = await browser.newPage();
  try {
    await page.setViewport({ width: 1280, height: 900 });

    // Set cookies
    await page.setCookie(
      { name: 'auth_token', value: process.env.X_AUTH_TOKEN, domain: '.x.com' },
      { name: 'ct0', value: process.env.X_CT0, domain: '.x.com' },
      { name: 'twid', value: process.env.X_TWID, domain: '.x.com' }
    );

    let lastTweetId = null;

    for (let i = 0; i < tweets.length; i++) {
      console.log('Publicando tweet ' + (i + 1) + '/' + tweets.length + '...');

      if (i === 0) {
        // First: go to home to establish session
        await page.goto('https://x.com/home', { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(r => setTimeout(r, 4000));
        // Then navigate to compose
        await page.goto('https://x.com/compose/tweet', { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(r => setTimeout(r, 3000));
      } else {
        // Reply to previous tweet
        await page.goto('https://x.com/napoleotics/status/' + lastTweetId, { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(r => setTimeout(r, 4000));
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
          const fileInput = await page.$('input[data-testid="fileInput"], input[type="file"]');
          if (fileInput) {

            // Setup network response listener to detect X server upload confirmation
            let mediaUploadDone = false;
            let mediaUploadError = false;
            const responseHandler = async (resp) => {
              try {
                const url = resp.url();
                if (url.includes('upload.x.com') || url.includes('/media/upload')) {
                  if (resp.status() >= 400) {
                    mediaUploadError = true;
                    console.log('[WARN] Upload HTTP error: ' + resp.status());
                    return;
                  }
                  const text = await resp.text().catch(() => '');
                  if (text.includes('media_id') || text.includes('expires_after_secs')) {
                    mediaUploadDone = true;
                    console.log('Upload confirmado por X server');
                  }
                }
              } catch(e) {}
            };
            page.on('response', responseHandler);

            if (mediaType === 'image' && validImages.length > 1) {
              await fileInput.uploadFile(...validImages);
              console.log(validImages.length + ' imagenes adjuntadas: ' + validImages.join(', '));
            } else {
              await fileInput.uploadFile(mediaPath);
              console.log((mediaType === 'video' ? 'Video' : 'Imagen') + ' adjuntado: ' + mediaPath);
            }

            if (mediaType === 'video') {
              const fileSize = fs.statSync(mediaPath).size;
              const sizeMB = (fileSize / (1024 * 1024)).toFixed(1);
              console.log('Tamano del video: ' + sizeMB + ' MB');
              const waitTime = Math.min(Math.max(15000, sizeMB * 10000 + 15000), 60000);
              console.log('Esperando ' + Math.round(waitTime/1000) + 's para video...');
              await new Promise(r => setTimeout(r, waitTime));
              try {
                const btnReady = await page.evaluate(() => {
                  const btn = document.querySelector('[data-testid="tweetButton"]');
                  return btn && !btn.disabled;
                });
                if (!btnReady) {
                  console.log('Esperando 15s adicionales para video...');
                  await new Promise(r => setTimeout(r, 15000));
                }
              } catch (e) {
                await new Promise(r => setTimeout(r, 10000));
              }
            } else {
              // Images: wait for X server confirmation (max 15s), fallback to 5s
              console.log('Esperando confirmacion de upload de imagen...');
              let waited = 0;
              while (!mediaUploadDone && !mediaUploadError && waited < 15000) {
                await new Promise(r => setTimeout(r, 500));
                waited += 500;
              }
              if (mediaUploadDone) {
                console.log('Imagen subida y confirmada en ' + waited + 'ms');
                await new Promise(r => setTimeout(r, 800)); // brief settle
              } else if (mediaUploadError) {
                console.log('[ERROR] Upload fallido — publicando sin imagen');
              } else {
                console.log('Upload sin confirmar despues de 15s — continuando');
                await new Promise(r => setTimeout(r, 3000));
              }
            }

            page.off('response', responseHandler);

          } else {
            console.log('No se encontro input de archivo — publicando sin media');
          }
        } catch (mediaErr) {
          if (mediaErr.message.includes('detached Frame')) {
            console.log('Frame recargado durante upload — probablemente OK');
            await new Promise(r => setTimeout(r, 5000));
          } else {
            console.log('Error adjuntando ' + mediaType + ': ' + mediaErr.message);
          }
        }
      }

      await new Promise(r => setTimeout(r, 1500));

      // Click publish — prefer tweetButton (main compose) over tweetButtonInline (always disabled)
      try {
        let btn = await page.$('[data-testid="tweetButton"]:not([disabled])');
        if (!btn) {
          // Fallback to either button
          btn = await page.waitForSelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]', { timeout: 10000 });
        }
        await btn.click();
      } catch (clickErr) {
        console.log('Reintentando click en publicar...');
        try {
          await new Promise(r => setTimeout(r, 3000));
          const btn2 = await page.waitForSelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]', { timeout: 15000 });
          await btn2.click();
        } catch (retryErr) {
          console.log('No se pudo hacer click: ' + retryErr.message);
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

      // Videos need more time after clicking publish
      const postWait = (i === 0 && mediaType === 'video') ? 15000 : 5000;
      await new Promise(r => setTimeout(r, postWait));

      // Capture tweet ID
      const currentUrl = page.url();
      const match = currentUrl.match(/status\/(\d+)/);
      if (match) {
        lastTweetId = match[1];
      } else {
        await page.goto('https://x.com/napoleotics', { waitUntil: 'domcontentloaded', timeout: 60000 });
        await new Promise(r => setTimeout(r, 3000));
        const links = await page.$$eval('a[href*="/napoleotics/status/"]', els =>
          els.map(el => el.href).filter(h => h.match(/\/status\/\d+$/))
        );
        if (links.length > 0) {
          const m = links[0].match(/status\/(\d+)/);
          if (m) lastTweetId = m[1];
        }
      }

      console.log('Tweet ' + (i + 1) + ' publicado. ID: ' + lastTweetId);

      // Random delay between tweets (8-15 seconds)
      if (i < tweets.length - 1) {
        const delay = 8000 + Math.floor(Math.random() * 7000);
        console.log('Esperando ' + Math.round(delay/1000) + 's...');
        await new Promise(r => setTimeout(r, delay));
      }
    }

  } finally {
    await browser.close();
  }
  console.log('Listo: ' + tweets.length + ' tweet(s) publicados.');
}

// Retry wrapper
async function postWithRetry(maxRetries = 3, retryDelay = 30000) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      await postThread();
      return;
    } catch (err) {
      console.error('Error en intento ' + attempt + '/' + maxRetries + ': ' + err.message);
      if (attempt < maxRetries) {
        console.log('Reintentando en ' + retryDelay / 1000 + 's...');
        await new Promise(r => setTimeout(r, retryDelay));
      } else {
        console.error('Todos los intentos fallaron.');
        process.exit(1);
      }
    }
  }
}

postWithRetry().catch(err => {
  console.error('Error fatal:', err.message);
  process.exit(1);
});
