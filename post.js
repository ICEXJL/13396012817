// Post Detail Page Scripts

document.addEventListener('DOMContentLoaded', () => {
    initCodeCopy();
    initTOC();
    initComments();
    initReadingProgress();
});

// Code Copy Functionality
function initCodeCopy() {
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const codeBlock = btn.closest('.code-block');
            if (!codeBlock) return;
            
            const code = codeBlock.querySelector('code');
            if (!code) return;
            
            try {
                await navigator.clipboard.writeText(code.textContent);
                
                // Show success feedback
                const originalText = btn.textContent;
                btn.textContent = '已复制!';
                btn.classList.add('copied');
                
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy code:', err);
                btn.textContent = '复制失败';
                setTimeout(() => {
                    btn.textContent = '复制';
                }, 2000);
            }
        });
    });
}

// Table of Contents Active State
function initTOC() {
    const headings = document.querySelectorAll('.post-content h2[id], .post-content h3[id]');
    const tocLinks = document.querySelectorAll('.toc-list a');
    
    if (!headings.length || !tocLinks.length) return;
    
    const observerOptions = {
        root: null,
        rootMargin: '-20% 0px -80% 0px',
        threshold: 0
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const id = entry.target.getAttribute('id');
                
                // Remove active class from all links
                tocLinks.forEach(link => link.classList.remove('active'));
                
                // Add active class to current link
                const activeLink = document.querySelector(`.toc-list a[href="#${id}"]`);
                if (activeLink) {
                    activeLink.classList.add('active');
                }
            }
        });
    }, observerOptions);
    
    headings.forEach(heading => observer.observe(heading));
    
    // Smooth scroll for TOC links
    tocLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                const offsetTop = targetElement.offsetTop - 100;
                window.scrollTo({
                    top: offsetTop,
                    behavior: 'smooth'
                });
            }
        });
    });
}

// Comments Functionality
function initComments() {
    const commentForm = document.querySelector('.comment-form');
    const commentInput = document.querySelector('.comment-input');
    const commentName = document.querySelector('.comment-name');
    const commentSubmit = document.querySelector('.comment-submit');
    const commentsList = document.querySelector('.comments-list');
    const commentsTitle = document.querySelector('.comments-title');
    
    if (!commentSubmit) return;
    
    commentSubmit.addEventListener('click', () => {
        const text = commentInput?.value.trim();
        const name = commentName?.value.trim() || '匿名用户';
        
        if (!text) {
            alert('请输入评论内容');
            return;
        }
        
        // Create new comment
        const commentItem = document.createElement('div');
        commentItem.className = 'comment-item';
        commentItem.style.animation = 'fadeIn 0.5s ease';
        
        const date = new Date().toLocaleDateString('zh-CN');
        const avatarSeed = Math.random().toString(36).substring(7);
        
        commentItem.innerHTML = `
            <div class="comment-avatar">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=${avatarSeed}" alt="用户头像">
            </div>
            <div class="comment-content">
                <div class="comment-header">
                    <span class="comment-author">${escapeHtml(name)}</span>
                    <span class="comment-date">${date}</span>
                </div>
                <p class="comment-text">${escapeHtml(text)}</p>
            </div>
        `;
        
        // Add to list
        commentsList.insertBefore(commentItem, commentsList.firstChild);
        
        // Update comment count
        const currentCount = parseInt(commentsTitle.textContent.match(/\d+/)[0]);
        commentsTitle.textContent = `评论 (${currentCount + 1})`;
        
        // Clear form
        commentInput.value = '';
        commentName.value = '';
        
        // Show success message
        showNotification('评论发表成功！');
    });
}

// Reading Progress Indicator
function initReadingProgress() {
    const progressBar = document.createElement('div');
    progressBar.className = 'reading-progress';
    progressBar.innerHTML = '<div class="reading-progress-bar"></div>';
    
    // Add styles
    const style = document.createElement('style');
    style.textContent = `
        .reading-progress {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background-color: var(--border-color);
            z-index: 1000;
        }
        .reading-progress-bar {
            height: 100%;
            background-color: var(--primary-color);
            width: 0%;
            transition: width 0.1s ease;
        }
    `;
    document.head.appendChild(style);
    document.body.appendChild(progressBar);
    
    const progressBarInner = progressBar.querySelector('.reading-progress-bar');
    
    function updateProgress() {
        const scrollTop = window.pageYOffset;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        const progress = (scrollTop / docHeight) * 100;
        progressBarInner.style.width = `${Math.min(progress, 100)}%`;
    }
    
    window.addEventListener('scroll', throttle(updateProgress, 50));
    updateProgress();
}

// Utility: Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Utility: Throttle
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

// Utility: Show Notification
function showNotification(message) {
    const notification = document.createElement('div');
    notification.className = 'notification';
    notification.textContent = message;
    
    // Add styles
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 24px;
        padding: 12px 24px;
        background-color: var(--primary-color);
        color: white;
        border-radius: 8px;
        font-weight: 500;
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    // Add animation styles
    if (!document.querySelector('#notification-styles')) {
        const style = document.createElement('style');
        style.id = 'notification-styles';
        style.textContent = `
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            @keyframes slideOut {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(100%);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// Image lazy loading
document.querySelectorAll('.post-content img').forEach(img => {
    img.loading = 'lazy';
    img.addEventListener('click', () => {
        // Simple lightbox functionality
        const lightbox = document.createElement('div');
        lightbox.className = 'lightbox';
        lightbox.innerHTML = `
            <div class="lightbox-overlay"></div>
            <img src="${img.src}" alt="${img.alt}" class="lightbox-img">
            <button class="lightbox-close">&times;</button>
        `;
        
        lightbox.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 2000;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        
        const overlay = lightbox.querySelector('.lightbox-overlay');
        overlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0, 0, 0, 0.9);
        `;
        
        const lightboxImg = lightbox.querySelector('.lightbox-img');
        lightboxImg.style.cssText = `
            max-width: 90%;
            max-height: 90%;
            object-fit: contain;
            z-index: 1;
        `;
        
        const closeBtn = lightbox.querySelector('.lightbox-close');
        closeBtn.style.cssText = `
            position: absolute;
            top: 20px;
            right: 20px;
            width: 40px;
            height: 40px;
            font-size: 2rem;
            color: white;
            background: none;
            border: none;
            cursor: pointer;
            z-index: 2;
        `;
        
        document.body.appendChild(lightbox);
        document.body.style.overflow = 'hidden';
        
        const closeLightbox = () => {
            lightbox.remove();
            document.body.style.overflow = '';
        };
        
        closeBtn.addEventListener('click', closeLightbox);
        overlay.addEventListener('click', closeLightbox);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeLightbox();
        });
    });
});

// Print article
function printArticle() {
    window.print();
}

// Share article
async function shareArticle(title, url) {
    if (navigator.share) {
        try {
            await navigator.share({
                title: title,
                url: url
            });
        } catch (err) {
            console.log('Share cancelled');
        }
    } else {
        // Fallback: copy to clipboard
        try {
            await navigator.clipboard.writeText(url);
            showNotification('链接已复制到剪贴板');
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }
}

// Export functions for global access
window.printArticle = printArticle;
window.shareArticle = shareArticle;
