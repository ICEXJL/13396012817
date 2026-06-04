// Blog Interactive Features

// DOM Elements
const searchBtn = document.getElementById('searchBtn');
const searchPanel = document.getElementById('searchPanel');
const searchClose = document.getElementById('searchClose');
const searchInput = document.getElementById('searchInput');

const menuBtn = document.getElementById('menuBtn');
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const sidebarClose = document.getElementById('sidebarClose');

const themeBtn = document.getElementById('themeBtn');
const themeSlider = document.getElementById('themeSlider');

const categoryMore = document.getElementById('categoryMore');
const tagMore = document.getElementById('tagMore');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSearch();
    initSidebar();
    initThemeSlider();
    initShowMore();
    initSmoothScroll();
});

// Theme Management
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    const savedHue = localStorage.getItem('primaryHue') || '250';
    
    document.documentElement.setAttribute('data-theme', savedTheme);
    document.documentElement.style.setProperty('--primary-hue', savedHue);
    
    if (themeSlider) {
        themeSlider.value = savedHue;
    }
    
    updateThemeIcon(savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    if (!themeBtn) return;
    
    const sunIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="5"></circle>
        <line x1="12" y1="1" x2="12" y2="3"></line>
        <line x1="12" y1="21" x2="12" y2="23"></line>
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
        <line x1="1" y1="12" x2="3" y2="12"></line>
        <line x1="21" y1="12" x2="23" y2="12"></line>
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
    </svg>`;
    
    const moonIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
    </svg>`;
    
    themeBtn.innerHTML = theme === 'dark' ? sunIcon : moonIcon;
}

if (themeBtn) {
    themeBtn.addEventListener('click', toggleTheme);
}

// Search Panel
function initSearch() {
    if (!searchBtn || !searchPanel) return;
    
    searchBtn.addEventListener('click', () => {
        searchPanel.classList.add('active');
        if (searchInput) {
            setTimeout(() => searchInput.focus(), 100);
        }
    });
    
    if (searchClose) {
        searchClose.addEventListener('click', closeSearch);
    }
    
    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && searchPanel.classList.contains('active')) {
            closeSearch();
        }
    });
    
    // Close on overlay click
    searchPanel.addEventListener('click', (e) => {
        if (e.target === searchPanel) {
            closeSearch();
        }
    });
}

function closeSearch() {
    if (searchPanel) {
        searchPanel.classList.remove('active');
    }
}

// Sidebar
function initSidebar() {
    if (!menuBtn || !sidebar) return;
    
    menuBtn.addEventListener('click', () => {
        sidebar.classList.add('active');
        document.body.style.overflow = 'hidden';
    });
    
    const closeSidebar = () => {
        sidebar.classList.remove('active');
        document.body.style.overflow = '';
    };
    
    if (sidebarClose) {
        sidebarClose.addEventListener('click', closeSidebar);
    }
    
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeSidebar);
    }
    
    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar.classList.contains('active')) {
            closeSidebar();
        }
    });
}

// Theme Color Slider
function initThemeSlider() {
    if (!themeSlider) return;
    
    themeSlider.addEventListener('input', (e) => {
        const hue = e.target.value;
        document.documentElement.style.setProperty('--primary-hue', hue);
        localStorage.setItem('primaryHue', hue);
    });
}

// Show More functionality
function initShowMore() {
    // Categories show more
    if (categoryMore) {
        categoryMore.addEventListener('click', () => {
            const categoriesList = document.querySelector('.categories-list');
            const hiddenCategories = [
                { name: '移动开发', count: 2 },
                { name: '云计算', count: 3 },
                { name: '安全', count: 1 },
                { name: '测试', count: 2 }
            ];
            
            hiddenCategories.forEach(cat => {
                const link = document.createElement('a');
                link.href = '#';
                link.className = 'category-item';
                link.innerHTML = `
                    <span class="category-name">${cat.name}</span>
                    <span class="category-count">${cat.count}</span>
                `;
                categoriesList.insertBefore(link, categoryMore);
            });
            
            categoryMore.style.display = 'none';
        });
    }
    
    // Tags show more
    if (tagMore) {
        tagMore.addEventListener('click', () => {
            const tagsList = document.querySelector('.tags-list');
            const hiddenTags = [
                'AWS', 'Azure', 'Nginx', 'Elasticsearch', 
                'Kafka', 'RabbitMQ', 'gRPC', 'Protobuf'
            ];
            
            hiddenTags.forEach(tag => {
                const link = document.createElement('a');
                link.href = '#';
                link.className = 'tag-item';
                link.textContent = tag;
                tagsList.insertBefore(link, tagMore);
            });
            
            tagMore.style.display = 'none';
        });
    }
}

// Smooth scroll for anchor links
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href === '#') return;
            
            e.preventDefault();
            const target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Search functionality
if (searchInput) {
    searchInput.addEventListener('input', debounce((e) => {
        const query = e.target.value.toLowerCase().trim();
        
        if (!query) {
            document.querySelectorAll('.post-card').forEach(card => {
                card.style.display = '';
            });
            return;
        }
        
        document.querySelectorAll('.post-card').forEach(card => {
            const title = card.querySelector('.post-title').textContent.toLowerCase();
            const excerpt = card.querySelector('.post-excerpt').textContent.toLowerCase();
            const category = card.querySelector('.post-category').textContent.toLowerCase();
            
            if (title.includes(query) || excerpt.includes(query) || category.includes(query)) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        });
    }, 300));
}

// Utility: Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Utility: Throttle function
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Navbar scroll effect
let lastScroll = 0;
const navbar = document.querySelector('.navbar');

window.addEventListener('scroll', throttle(() => {
    const currentScroll = window.pageYOffset;
    
    if (currentScroll > 100) {
        navbar.style.boxShadow = 'var(--shadow-md)';
    } else {
        navbar.style.boxShadow = 'none';
    }
    
    lastScroll = currentScroll;
}, 100));

// Add reading time estimation
function estimateReadingTime(text) {
    const wordsPerMinute = 200;
    const words = text.trim().split(/\s+/).length;
    return Math.ceil(words / wordsPerMinute);
}

// Intersection Observer for fade-in animations
const observerOptions = {
    root: null,
    rootMargin: '0px',
    threshold: 0.1
};

const fadeInObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Observe all post cards
document.querySelectorAll('.post-card').forEach(card => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    fadeInObserver.observe(card);
});

// Copy code functionality for future code blocks
document.addEventListener('click', (e) => {
    if (e.target.matches('.copy-code-btn')) {
        const codeBlock = e.target.closest('.code-block');
        if (codeBlock) {
            const code = codeBlock.querySelector('code').textContent;
            navigator.clipboard.writeText(code).then(() => {
                const btn = e.target;
                const originalText = btn.textContent;
                btn.textContent = '已复制!';
                setTimeout(() => {
                    btn.textContent = originalText;
                }, 2000);
            });
        }
    }
});

// Print styles
window.addEventListener('beforeprint', () => {
    document.documentElement.setAttribute('data-theme', 'light');
});

window.addEventListener('afterprint', () => {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
});

// Service Worker registration for PWA (optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        // Uncomment to enable PWA functionality
        // navigator.serviceWorker.register('/sw.js');
    });
}

// Export functions for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        toggleTheme,
        closeSearch,
        debounce,
        throttle,
        estimateReadingTime
    };
}
