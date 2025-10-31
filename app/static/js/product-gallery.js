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

  /**
   * Initialize gallery with navigation controls
   * Supports both card galleries (.js-card-gallery) and detail galleries (.js-gallery)
   * Both start with mockup view: idx -1 = mockup, 0 = design-only
   */
  function initGallery(galleryEl) {
    const frames = Array.from(galleryEl.querySelectorAll('img[data-frame]'));
    const mock = galleryEl.querySelector('.mockup-wrap') || galleryEl.querySelector('#mockup-wrap');
    const isDetailView = galleryEl.classList.contains('js-gallery');
    const isCardView = galleryEl.classList.contains('js-card-gallery');
    
    if (!frames.length && !mock) return;
    
    // Both card and detail views start at mockup (-1)
    // -1 = mockup (main image), 0 = design-only square PNG
    let idx = -1;
    
    // Initialize mockup with default white color for cards
    if (isCardView && mock) {
      const base = mock.querySelector('.mockup-base');
      const design = mock.querySelector('.mockup-design');
      if (base) {
        base.onerror = function() {
          this.onerror = null;
          this.src = MOCKUP_BASES.white;
        };
        base.src = MOCKUP_BASES.white;
      }
      // Design src should already be set from data-design-src attribute
    }
    
    const render = () => {
      frames.forEach(im => im.classList.add('hidden'));
      if (mock) mock.classList.add('hidden');
      
      if (idx === -1) {
        // Show mockup (for both detail and card views)
        if (mock) mock.classList.remove('hidden');
      } else if (frames[idx]) {
        frames[idx].classList.remove('hidden');
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
        // From mockup, go to last frame (design-only)
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
        // From mockup, go to design-only (frame 0)
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
    
    render();
    
    return { render, idx: () => idx, setIdx: (i) => { idx = i; render(); } };
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
    
    const frames = Array.from(galleryEl.querySelectorAll('img[data-frame]'));
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
    
    // Get design image source from mockup-design element or first frame
    const mockDesign = gallery.querySelector('.mockup-design') || gallery.querySelector('#mockup-design');
    const designSrc = mockDesign?.getAttribute('data-design-src') || 
                     mockDesign?.getAttribute('src') || 
                     (gallery.querySelector('img[data-frame]')?.getAttribute('src') || '');
    
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
        // Ensure mockup is visible and hide frames
        if (mock) {
          mock.classList.remove('hidden');
          const frames = gallery.querySelectorAll('img[data-frame]');
          frames.forEach(im => im.classList.add('hidden'));
        }
        
        // Update card link URL params
        try {
          const href = cardEl.getAttribute('href') || '';
          if (href && href !== '#') {
            const url = new URL(href, window.location.origin);
            url.searchParams.set('color', c);
            url.searchParams.set('size', inputSize?.value || 'L');
            const vid = inputVariant?.value || '';
            if (vid) url.searchParams.set('vid', String(vid));
            cardEl.setAttribute('href', url.pathname + url.search);
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
          const href = cardEl.getAttribute('href') || '';
          if (href && href !== '#') {
            const url = new URL(href, window.location.origin);
            url.searchParams.set('size', sizeSelect.value);
            const vid = inputVariant?.value || '';
            if (vid) url.searchParams.set('vid', String(vid));
            cardEl.setAttribute('href', url.pathname + url.search);
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
  }

  /**
   * Initialize mockup for product detail page with default color
   */
  function initDetailMockup(defaultColor, designSrc) {
    const gallery = document.querySelector('.js-gallery');
    if (!gallery) return;
    
    // Initialize mockup with default color
    updateMockup(gallery, defaultColor || 'white', designSrc);
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
      const defaultColor = document.getElementById('color-select')?.value || 'white';
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

  // Export functions for use in templates
  window.ProductGallery = {
    initGallery,
    updateMockup,
    hideMockup,
    initCardColorSwatches,
    initDetailColorSwatches,
    initDetailMockup,
    MOCKUP_BASES
  };

})();

