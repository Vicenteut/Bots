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
  /**
   * After uploading a video, X shows a progress bar / processing indicator.
   * We wait until the video thumbnail appears or the progress disappears.
   */
  const startTime = Date.now();
  console.log('Esperando procesamiento de video...');

  while (Date.now() - startTime < timeout) {
    // Check if there's still a progress indicator
    const processing = await page.evaluate(() => {
      // X shows a circular progress or "Processing" text during upload
      const progressBar = document.querySelector('[role="progressbar"]');
      const processingText = document.body.innerText.includes('Uploading') ||
                             document.body.innerText.includes('Processing');
      return progressBar !== null || processingText;
    });

    if (!processing) {
      // Double check: look for the media preview (thumbnail)
      const hasMedia = await page.evaluate(() => {
        const mediaPreview = document.querySelector('[data-testid="attachments"]') ||
                             document.querySelector('video') ||
                             document.querySelector('[data-testid="mediaPreview"]');
        return mediaPreview !== null;
      });

      if (hasMedia) {
        console.log('Video procesado OK');
        return true;
      }
    }

    // Check for error
    const hasError = await page.evaluate(() => {
      const errorText = document.body.innerText;
      return errorText.includes('Unable to upload') ||
             errorText.includes('try again') ||
             errorText.includes('error');
    });

    if (hasError) {
      console.log('Error detectado durante procesamiento de video');
      return false;
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
      // First tweet: go to compose
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
            // Videos need much more time to upload + process
            const fileSize = fs.statSync(mediaPath).size;
            const sizeMB = (fileSize / (1024 * 1024)).toFixed(1);
            console.log(`Tamano del video: ${sizeMB} MB`);

            // Wait for upload + processing (up to 2 minutes)
            const processed = await waitForVideoProcessing(page, 120000);
            if (!processed) {
              console.log('AVISO: Video puede no haberse procesado completamente');
            }
          } else {
            // Images are fast
            await new Promise(r => setTimeout(r, 5000));
          }
        } else {
          console.log('No se encontro el input de archivo, publicando sin media');
        }
      } catch (mediaErr) {
        console.log(`Error al adjuntar ${mediaType}: ${mediaErr.message}`);
      }
    }

    await new Promise(r => setTimeout(r, 1500));

    // Click publish
    const btn = await page.waitForSelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]', { timeout: 10000 });
    await btn.click();

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
