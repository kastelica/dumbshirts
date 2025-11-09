/**
 * Unified Product Gallery and Color Swatch System
 * Handles image carousel navigation and color mockup previews across all product pages
 */

(function() {
  'use strict';

  // T-shirt base images for mockup system
  const MOCKUP_BASES = {
    white: '/static/uploads/whitetshirt.png',
    black: '/static/uploads/blacktshirt.png',
    heather: '/static/uploads/heathertshirt.png',
    grey: '/static/uploads/greytshirt.png',
    gray: '/static/uploads/greytshirt.png',
    red: '/static/uploads/redtshirt.png',
    blue: '/static/uploads/bluetshirt.png',
    pink: '/static/uploads/pinktshirt.png'
  };

  // Color to hex mapping for background colors
  const COLOR_BACKGROUNDS = {
    white: '#ffffff',
    black: '#000000',
    heather: '#9ca3af',
    grey: '#9ca3af',
    gray: '#9ca3af',
    red: '#ef4444',
    blue: '#3b82f6',
    pink: '#ec4899'
  };

  /**
   * Create or update the colored background for design-only frame
   */
  function updateDesignBackground(galleryEl, color) {
    const container = galleryEl.querySelector('.aspect-square') || galleryEl;
    let bgDiv = container.querySelector('.design-bg-color');
    
    if (!bgDiv) {
      bgDiv = document.createElement('div');
      bgDiv.className = 'design-bg-color absolute inset-0 z-[1]';
      // Ensure container has relative positioning
      if (container.style.position !== 'relative' && !container.classList.contains('relative')) {
        container.style.position = 'relative';
      }
      // Insert at beginning so it's behind images (z-[1] above base background)
      container.insertBefore(bgDiv, container.firstChild);
    }
    
    const colorLower = (color || 'white').toLowerCase();
    const bgColor = COLOR_BACKGROUNDS[colorLower] || COLOR_BACKGROUNDS.white;
    bgDiv.style.backgroundColor = bgColor;
    
    // Store current color on gallery element for reference
    galleryEl.setAttribute('data-current-color', colorLower);
  }

  /**
   * Initialize gallery with navigation controls
   * Supports both card galleries (.js-card-gallery) and detail galleries (.js-gallery)
   * Both start with mockup view: idx -1 = mockup, 0 = design-only
   */
  function initGallery(galleryEl) {
    let frames = Array.from(galleryEl.querySelectorAll('[data-frame]'));

    // If a product video is available, append it as an additional frame (after design-only)
    try {
      const videoSrc = (window.PRODUCT_DATA && window.PRODUCT_DATA.videoSrc) ? String(window.PRODUCT_DATA.videoSrc) : '';
      const alreadyHasVideo = !!galleryEl.querySelector('video[data-frame]');
      if (videoSrc && !alreadyHasVideo) {
        const container = galleryEl.querySelector('.aspect-square') || galleryEl;
        const vid = document.createElement('video');
        vid.setAttribute('data-frame', 'video');
        vid.className = 'w-full h-full object-contain hidden';
        vid.src = videoSrc;
        vid.controls = true;
        vid.playsInline = true;
        vid.preload = 'metadata';
        container.appendChild(vid);
        frames = Array.from(galleryEl.querySelectorAll('[data-frame]'));
      }
    } catch (_e) {}
    const mock = galleryEl.querySelector('.mockup-wrap') || galleryEl.querySelector('#mockup-wrap');
    const isDetailView = galleryEl.classList.contains('js-gallery');
    const isCardView = galleryEl.classList.contains('js-card-gallery');
    
    if (!frames.length && !mock) return;
    
    // Both card and detail views start at mockup (-1)
    // -1 = mockup (main image), 0 = design-only square PNG
    let idx = -1;
    
    // Track current selected color for background updates
    let currentColor = 'white';
    
    // Initialize mockup with auto-selected color for cards
    if (isCardView && mock) {
      const base = mock.querySelector('.mockup-base');
      const design = mock.querySelector('.mockup-design');
      const cardEl = galleryEl.closest('.group') || galleryEl.closest('a');
      
      // Get auto-selected color from card data attribute
      let autoColor = 'white';
      if (cardEl) {
        const dataColor = cardEl.getAttribute('data-auto-color');
        if (dataColor) {
          autoColor = dataColor.toLowerCase();
          currentColor = autoColor;
        }
      }
      
      if (base) {
        base.onerror = function() {
          this.onerror = null;
          this.src = MOCKUP_BASES.white;
        };
        const baseSrc = MOCKUP_BASES[autoColor] || MOCKUP_BASES.white;
        base.src = baseSrc;
      }
      // Set design src from data-design-src attribute (like product_detail)
      if (design) {
        const designSrc = design.getAttribute('data-design-src') || design.getAttribute('src') || '';
        if (designSrc) {
          design.src = designSrc;
        }
      }
      
      // Initialize background color for design frame
      updateDesignBackground(galleryEl, currentColor);
    } else if (isDetailView) {
      // For detail view, get initial color from select or default to white
      const colorSelect = document.getElementById('color-select');
      if (colorSelect) {
        currentColor = (colorSelect.value || 'white').toLowerCase();
      }
      updateDesignBackground(galleryEl, currentColor);
    }
    
    const render = () => {
      frames.forEach(im => im.classList.add('hidden'));
      if (mock) mock.classList.add('hidden');
      
      const container = galleryEl.querySelector('.aspect-square') || galleryEl;
      const bgDiv = container.querySelector('.design-bg-color');
      
      if (idx === -1) {
        // Show mockup (for both detail and card views)
        if (mock) mock.classList.remove('hidden');
        // Hide background color when showing mockup
        if (bgDiv) bgDiv.classList.add('hidden');
      } else if (frames[idx]) {
        frames[idx].classList.remove('hidden');
        // Ensure frame image is above background but below navigation buttons (z-index)
        frames[idx].style.position = 'relative';
        frames[idx].style.zIndex = '2';
        // Ensure buttons stay on top (they have z-20 in HTML)
        const prevBtn = galleryEl.querySelector('[data-action="prev"]');
        const nextBtn = galleryEl.querySelector('[data-action="next"]');
        if (prevBtn) prevBtn.style.zIndex = '20';
        if (nextBtn) nextBtn.style.zIndex = '20';
        // Show background color when showing design-only frame
        // Get current color from attribute or use tracked color
        const savedColor = galleryEl.getAttribute('data-current-color') || currentColor;
        if (bgDiv) {
          bgDiv.classList.remove('hidden');
          // Update background color to current selected color
          const colorLower = savedColor.toLowerCase();
          const bgColor = COLOR_BACKGROUNDS[colorLower] || COLOR_BACKGROUNDS.white;
          bgDiv.style.backgroundColor = bgColor;
        } else {
          // Create and show background if it doesn't exist
          updateDesignBackground(galleryEl, savedColor);
        }
      }
    };
    
    const prevBtn = galleryEl.querySelector('[data-action="prev"]');
    const nextBtn = galleryEl.querySelector('[data-action="next"]');
    
    const handlePrev = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (idx === -1) {
        // From mockup, go to last frame (design-only/video)
        idx = frames.length > 0 ? frames.length - 1 : 0;
      } else if (idx > 0) {
        idx--;
      } else if (idx === 0) {
        // From design-only, go back to mockup
        idx = -1;
      }
      render();
    };
    
    const handleNext = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (idx === -1) {
        // From mockup, go to first frame (design-only)
        idx = frames.length > 0 ? 0 : -1;
      } else if (idx < frames.length - 1) {
        idx++;
      } else if (idx === frames.length - 1) {
        // From last frame, go back to mockup
        idx = -1;
      }
      render();
    };
    
    if (prevBtn) prevBtn.addEventListener('click', handlePrev);
    if (nextBtn) nextBtn.addEventListener('click', handleNext);
    
    // Lightbox: open on click/tap of the gallery area (excluding nav buttons)
    try {
      galleryEl.addEventListener('click', function(e){
        const t = e.target;
        if (t && t.closest && (t.closest('[data-action="prev"]') || t.closest('[data-action="next"]'))) {
          return; // ignore clicks on nav
        }
        openLightboxFromGallery(galleryEl, idx);
      });
    } catch (e) {}
    
    render();
    
    // Expose method to update color (for swatch changes)
    return { 
      render, 
      idx: () => idx, 
      setIdx: (i) => { idx = i; render(); },
      setColor: (c) => { 
        currentColor = (c || 'white').toLowerCase();
        galleryEl.setAttribute('data-current-color', currentColor);
        // If currently showing design frame, update background
        if (idx !== -1) {
          updateDesignBackground(galleryEl, currentColor);
        }
      }
    };
  }

  /**
   * Build and show a lightbox using the current gallery view (mockup or frame)
   */
  function openLightboxFromGallery(galleryEl, currentIdx){
    let lb = document.getElementById('gallery-lightbox');
    if(!lb){
      // Template should have injected it; if not present, bail
      return;
    }
    const lbImg = document.getElementById('lightbox-img');
    const lbMock = document.getElementById('lightbox-mockup');
    const lbBase = document.getElementById('lightbox-base');
    const lbDesign = document.getElementById('lightbox-design');
    if(!lbImg || !lbMock || !lbBase || !lbDesign) return;

    // Determine if mockup is visible
    const mock = galleryEl.querySelector('.mockup-wrap') || galleryEl.querySelector('#mockup-wrap');
    const isMockup = mock && !mock.classList.contains('hidden');

    // Determine current color and design src
    const colorEl = document.getElementById('color-select');
    const color = (colorEl && colorEl.value ? colorEl.value : (galleryEl.getAttribute('data-current-color') || 'white')).toLowerCase();
    const designEl = galleryEl.querySelector('.mockup-design') || galleryEl.querySelector('#mockup-design');
    const designSrc = (designEl && (designEl.getAttribute('src') || designEl.getAttribute('data-design-src'))) || '';

    if(isMockup){
      // Show mockup in lightbox
      const baseSrc = MOCKUP_BASES[color] || MOCKUP_BASES.white;
      lbBase.onerror = function(){ this.onerror=null; this.src = MOCKUP_BASES.white; };
      lbBase.src = baseSrc;
      if (designSrc) lbDesign.src = designSrc;
      lbMock.classList.remove('hidden');
      lbImg.classList.add('hidden');
    } else {
      // Find visible frame (image or video)
      const frame = Array.from(galleryEl.querySelectorAll('[data-frame]')).find(el => !el.classList.contains('hidden'));
      if (frame && frame.tagName && frame.tagName.toLowerCase() === 'video') {
        // Ensure a lightbox video element exists
        let lbVid = document.getElementById('lightbox-video');
        const container = lb.closest('.relative') || lb;
        if (!lbVid) {
          // Create within the image area wrapper (same absolute layout as img)
          const imgArea = lb.querySelector('.relative.w-full');
          const area = imgArea || lb;
          lbVid = document.createElement('video');
          lbVid.id = 'lightbox-video';
          lbVid.className = 'absolute inset-0 w-full h-full object-contain';
          lbVid.controls = true;
          lbVid.playsInline = true;
          lbVid.preload = 'metadata';
          area.insertBefore(lbVid, area.firstChild);
        }
        lbVid.src = frame.getAttribute('src') || frame.src || '';
        // Show video; hide mockup and image
        lbMock.classList.add('hidden');
        lbImg.classList.add('hidden');
        lbVid.classList.remove('hidden');
      } else {
        // Image frame
        const src = frame ? (frame.getAttribute('src') || '') : '';
        if (src) lbImg.src = src;
        // Hide any lightbox video if present
        const lbVid = document.getElementById('lightbox-video');
        if (lbVid) lbVid.classList.add('hidden');
        lbImg.classList.remove('hidden');
        lbMock.classList.add('hidden');
      }
    }

    // Wire close interactions
    const closeEl = document.getElementById('lightbox-close');
    const overlay = lb.querySelector('[data-close]');
    const buyBtn = document.getElementById('lightbox-buy');
    function hide(){ lb.classList.add('hidden'); }
    if (closeEl) closeEl.onclick = hide;
    if (overlay) overlay.onclick = hide;
    try {
      document.addEventListener('keydown', function onEsc(ev){
        if (ev.key === 'Escape') { hide(); document.removeEventListener('keydown', onEsc); }
      });
    } catch(e){}

    // Buy Now CTA inside lightbox: set flag and submit existing form
    if (buyBtn) {
      buyBtn.onclick = function(){
        try {
          const flag = document.getElementById('buy-now-flag');
          if (flag) flag.value = '1';
          const form = document.getElementById('add-form');
          if (form) form.submit();
        } catch(e){}
      };
    }

    lb.classList.remove('hidden');
  }

  /**
   * Update mockup overlay with selected color
   * Updates the base t-shirt color but doesn't change visibility - that's handled by gallery navigation
   */
  function updateMockup(galleryEl, color, designSrc) {
    const mock = galleryEl.querySelector('.mockup-wrap') || galleryEl.querySelector('#mockup-wrap');
    if (!mock) return;
    
    const base = mock.querySelector('.mockup-base') || mock.querySelector('#mockup-base');
    const design = mock.querySelector('.mockup-design') || mock.querySelector('#mockup-design');
    
    const colorLower = (color || 'white').toLowerCase();
    const baseSrc = MOCKUP_BASES[colorLower] || MOCKUP_BASES.white;
    
    if (base) {
      base.onerror = function() {
        this.onerror = null;
        this.src = MOCKUP_BASES.white;
      };
      base.src = baseSrc;
    }
    
    if (design && designSrc) {
      design.src = designSrc;
    }
    
    // Note: We don't change visibility here - that's handled by gallery navigation
    // The mockup base color just updates to reflect the selected color
  }

  /**
   * Hide mockup and show image frames
   */
  function hideMockup(galleryEl) {
    const mock = galleryEl.querySelector('.mockup-wrap') || galleryEl.querySelector('#mockup-wrap');
    if (mock) mock.classList.add('hidden');
    
    const frames = Array.from(galleryEl.querySelectorAll('[data-frame]'));
    if (frames.length > 0) {
      frames.forEach(im => im.classList.add('hidden'));
      frames[0].classList.remove('hidden');
    }
  }

  /**
   * Initialize color swatch system for product cards
   */
  function initCardColorSwatches(cardEl) {
    const wrap = cardEl.querySelector('.js-swatch-wrap');
    if (!wrap) return;
    
    // Parse variant mappings from data attributes
    let colorMap = {};
    let sizeColorToVid = {};
    
    try {
      colorMap = JSON.parse(wrap.getAttribute('data-card-color-map') || '{}');
      sizeColorToVid = JSON.parse(wrap.getAttribute('data-card-variant-map') || '{}');
    } catch (e) {
      console.warn('Failed to parse variant maps', e);
    }
    
    const inputVariant = cardEl.querySelector('.js-variant-id');
    const inputColor = cardEl.querySelector('.js-color-val');
    const inputSize = cardEl.querySelector('.js-size-val');
    const sizeSelect = cardEl.querySelector('.js-size-select');
    const gallery = cardEl.querySelector('.js-card-gallery') || cardEl.querySelector('.js-gallery');
    
    if (!gallery) return;
    
    // cardEl should be the <a> tag, but ensure we have it
    const linkEl = cardEl.tagName === 'A' ? cardEl : cardEl.closest('a');
    
    // Get auto-selected color from card data attribute
    let autoColor = (inputColor?.value || 'white').toLowerCase();
    const dataAutoColor = cardEl.getAttribute('data-auto-color');
    if (dataAutoColor) {
      autoColor = dataAutoColor.toLowerCase();
      // Update hidden color input to match auto-selected color
      if (inputColor) {
        inputColor.value = autoColor;
      }
    }
    
    // Get design image source from mockup-design element or first frame
    const mockDesign = gallery.querySelector('.mockup-design') || gallery.querySelector('#mockup-design');
    const designSrc = mockDesign?.getAttribute('data-design-src') || 
                     mockDesign?.getAttribute('src') || 
                     (gallery.querySelector('img[data-frame]')?.getAttribute('src') || '');
    
    // Mark the auto-selected color swatch as active
    wrap.querySelectorAll('[data-color]').forEach(btn => {
      const btnColor = (btn.getAttribute('data-color') || '').toLowerCase();
      if (btnColor === autoColor) {
        btn.classList.add('ring-2', 'ring-white');
        // Update variant if needed
        const chosenSize = (inputSize?.value || 'L').toLowerCase();
        const comboKey = `${chosenSize}|${autoColor}`;
        const mapped = sizeColorToVid[comboKey] || colorMap[autoColor];
        if (mapped && inputVariant) {
          inputVariant.value = mapped;
        }
      } else {
        btn.classList.remove('ring-2', 'ring-white');
      }
    });
    
    // Prevent navigation when clicking size dropdown inside card link
    try {
      cardEl.addEventListener('click', function(e) {
        const target = e.target;
        if (target && (target.closest && target.closest('.js-size-select'))) {
          e.preventDefault();
        }
      }, true);
    } catch (e) {}
    
    // Handle color swatch clicks
    wrap.querySelectorAll('[data-color]').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const c = (btn.getAttribute('data-color') || '').toLowerCase();
        
        // Update variant based on size+color or just color
        const chosenSize = (inputSize?.value || 'L').toLowerCase();
        const comboKey = `${chosenSize}|${c}`;
        const mapped = sizeColorToVid[comboKey] || colorMap[c];
        
        if (mapped && inputVariant) {
          inputVariant.value = mapped;
        }
        if (inputColor) {
          inputColor.value = c;
        }
        
        // Update active swatch visual
        wrap.querySelectorAll('[data-color]').forEach(b => {
          b.classList.remove('ring-2', 'ring-white');
        });
        btn.classList.add('ring-2', 'ring-white');
        
        // Show mockup overlay for selected color
        updateMockup(gallery, c, designSrc);
        // Update background color for design frame
        updateDesignBackground(gallery, c);
        // Store color on gallery for when frame switches
        gallery.setAttribute('data-current-color', c.toLowerCase());
        // Ensure mockup is visible and hide frames
        const mock = gallery.querySelector('.mockup-wrap') || gallery.querySelector('#mockup-wrap');
        if (mock) {
          mock.classList.remove('hidden');
          const frames = gallery.querySelectorAll('img[data-frame]');
          frames.forEach(im => im.classList.add('hidden'));
        }
        
        // Update card link URL params
        try {
          if (linkEl) {
            const href = linkEl.getAttribute('href') || '';
            if (href && href !== '#') {
              const url = new URL(href, window.location.origin);
              url.searchParams.set('color', c);
              url.searchParams.set('size', inputSize?.value || 'L');
              const vid = inputVariant?.value || '';
              if (vid) url.searchParams.set('vid', String(vid));
              linkEl.setAttribute('href', url.pathname + url.search);
              // Also update data-auto-color to reflect current selection
              linkEl.setAttribute('data-auto-color', c);
            }
          }
        } catch (e) {}
      });
    });
    
    // Handle size changes
    if (sizeSelect) {
      sizeSelect.addEventListener('change', function() {
        const sz = (sizeSelect.value || 'L').toLowerCase();
        if (inputSize) inputSize.value = sizeSelect.value;
        
        const c = (inputColor?.value || 'white').toLowerCase();
        const mapped = sizeColorToVid[`${sz}|${c}`] || colorMap[c];
        if (mapped && inputVariant) {
          inputVariant.value = mapped;
        }
        
        // Update card link params
        try {
          if (linkEl) {
            const href = linkEl.getAttribute('href') || '';
            if (href && href !== '#') {
              const url = new URL(href, window.location.origin);
              url.searchParams.set('size', sizeSelect.value);
              const vid = inputVariant?.value || '';
              if (vid) url.searchParams.set('vid', String(vid));
              linkEl.setAttribute('href', url.pathname + url.search);
            }
          }
        } catch (e) {}
      });
    }
  }

  /**
   * Initialize color swatches for product detail page
   */
  function initDetailColorSwatches(productData) {
    const colorSwatchesEl = document.getElementById('color-swatches');
    const colorSelectEl = document.getElementById('color-select');
    const colorFieldEl = document.getElementById('color-field');
    const sizeSelect = document.getElementById('size-select');
    const sizeField = document.getElementById('size-field');
    const variantSelect = document.getElementById('variant-select');
    const gallery = document.querySelector('.js-gallery');
    const productUidInput = document.getElementById('productUidInput');
    
    if (!colorSwatchesEl || !colorSelectEl) return;
    
    const colors = [
      { key: 'white', hex: '#ffffff' },
      { key: 'black', hex: '#000000' },
      { key: 'heather', hex: '#9ca3af' },
      { key: 'red', hex: '#ef4444' },
      { key: 'blue', hex: '#3b82f6' }
    ];
    
    // Get design source from template data
    const designSrc = productData?.designSrc || '';
    
    // Build swatches
    colorSwatchesEl.innerHTML = '';
    colors.forEach(c => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'h-8 rounded border border-gray-700';
      btn.style.backgroundColor = c.hex;
      btn.setAttribute('aria-label', c.key);
      btn.setAttribute('data-color', c.key);
      
      btn.addEventListener('click', () => {
        const newColor = c.key;
        colorSelectEl.value = newColor;
        if (colorFieldEl) colorFieldEl.value = newColor;
        
        // Update active swatch
        Array.from(colorSwatchesEl.children).forEach(el => {
          el.classList.remove('ring-2', 'ring-white');
        });
        btn.classList.add('ring-2', 'ring-white');
        
        // Update variant mapping
        if (productData?.sizeColorToVariantId && sizeSelect && variantSelect) {
          const size = (sizeSelect.value || 'L').toLowerCase();
          const key = `${size}|${newColor}`;
          const vid = productData.sizeColorToVariantId[key] || productData.colorToVariantId[newColor] || '';
          if (vid) variantSelect.value = String(vid);
        }
        
        // Update mockup base color (always update color, but only show if we're on mockup view)
        if (gallery) {
          updateMockup(gallery, newColor, designSrc);
          // Update background color for design frame
          updateDesignBackground(gallery, newColor);
          // If we're currently showing the mockup, keep it visible; otherwise stay on current frame
          const isDetailView = gallery.classList.contains('js-gallery');
          if (isDetailView) {
            // Check if we're currently on mockup view (idx -1)
            // We'll get the gallery state and if on mockup, refresh it; otherwise leave as is
            const mock = gallery.querySelector('.mockup-wrap') || gallery.querySelector('#mockup-wrap');
            if (mock && !mock.classList.contains('hidden')) {
              // We're on mockup view, update it but keep it visible
              // Mockup is already updated above, just ensure it's visible
              mock.classList.remove('hidden');
              // Hide any frames
              const frames = gallery.querySelectorAll('img[data-frame]');
              frames.forEach(im => im.classList.add('hidden'));
            }
          }
        }
        
        // Call custom callback if it exists (for product_detail page specific logic)
        if (typeof window.updateProductUid === 'function') {
          window.updateProductUid();
        }
      });
      
      if (colorSelectEl.value === c.key) {
        btn.classList.add('ring-2', 'ring-white');
      }
      
      colorSwatchesEl.appendChild(btn);
    });
    
    // Set active swatch based on initial color from URL or select value
    const initialColor = productData?.initialColor || colorSelectEl?.value || 'white';
    const activeBtn = colorSwatchesEl.querySelector(`[data-color="${initialColor.toLowerCase()}"]`);
    if (activeBtn) {
      activeBtn.classList.add('ring-2', 'ring-white');
      // Ensure all others are not active
      Array.from(colorSwatchesEl.children).forEach(el => {
        if (el !== activeBtn) {
          el.classList.remove('ring-2', 'ring-white');
        }
      });
    }
  }

  /**
   * Initialize mockup for product detail page with default color
   */
  function initDetailMockup(defaultColor, designSrc) {
    const gallery = document.querySelector('.js-gallery');
    if (!gallery) return;
    
    // Initialize mockup with default color
    updateMockup(gallery, defaultColor || 'white', designSrc);
    // Initialize background color
    updateDesignBackground(gallery, defaultColor || 'white');
  }

  /**
   * Main initialization function
   */
  function init() {
    // Initialize all galleries
    document.querySelectorAll('.js-card-gallery, .js-gallery').forEach(gallery => {
      initGallery(gallery);
    });
    
    // Initialize color swatches for product cards
    document.querySelectorAll('.group').forEach(card => {
      initCardColorSwatches(card);
    });
    
    // Product detail page initialization
    if (document.getElementById('color-swatches') && window.PRODUCT_DATA) {
      // Use initialColor from URL params if available, otherwise use select value, otherwise default to white
      const defaultColor = window.PRODUCT_DATA.initialColor || 
                          (document.getElementById('color-select')?.value || 'white');
      initDetailMockup(defaultColor, window.PRODUCT_DATA.designSrc);
      initDetailColorSwatches(window.PRODUCT_DATA);
    }
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Global Meta Pixel AddToCart tracking for product cards
  // Listens for submits on forms with class .js-add-to-cart-form
  try {
    document.addEventListener('submit', function(e){
      let form = e.target;
      if (!form || (form.tagName !== 'FORM')) {
        form = form && form.closest ? form.closest('.js-add-to-cart-form') : null;
      }
      if (!form || !form.classList || !form.classList.contains('js-add-to-cart-form')) return;
      try {
        // content_ids should be product IDs
        const pid = form.getAttribute('data-product-id') || '';
        if (typeof fbq === 'function' && pid) {
          fbq('track', 'AddToCart', {
            content_ids: [String(pid)],
            content_type: 'product'
          });
        }
      } catch (_err) {}
    }, true); // capture to fire early
  } catch (_e) {}

  // Export functions for use in templates
  window.ProductGallery = {
    initGallery,
    updateMockup,
    updateDesignBackground,
    hideMockup,
    initCardColorSwatches,
    initDetailColorSwatches,
    initDetailMockup,
    MOCKUP_BASES,
    COLOR_BACKGROUNDS
  };

})();

