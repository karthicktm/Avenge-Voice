/**
 * AVENGE AI - Scroll Animations & Interactions
 * Smooth fade-in animations and interactive elements
 */

// Intersection Observer for scroll animations
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry, index) => {
        if (entry.isIntersecting) {
            // Add stagger delay for grid items
            setTimeout(() => {
                entry.target.classList.add('visible');
            }, index * 100);
        }
    });
}, observerOptions);

// Observe all animatable elements
document.addEventListener('DOMContentLoaded', () => {
    // Feature cards
    const featureCards = document.querySelectorAll('.feature-card');
    featureCards.forEach(card => observer.observe(card));

    // Pricing cards
    const pricingCards = document.querySelectorAll('.pricing-card');
    pricingCards.forEach(card => observer.observe(card));

    // Integration items
    const integrationItems = document.querySelectorAll('.integration-item');
    integrationItems.forEach(item => observer.observe(item));

    // Smooth scroll for navigation links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const href = this.getAttribute('href');

            // Skip if it's just "#"
            if (href === '#') {
                e.preventDefault();
                return;
            }

            const target = document.querySelector(href);
            if (target) {
                e.preventDefault();
                const navHeight = document.querySelector('.nav').offsetHeight;
                const targetPosition = target.offsetTop - navHeight;

                window.scrollTo({
                    top: targetPosition,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Add scroll effect to navigation
    let lastScroll = 0;
    const nav = document.querySelector('.nav');

    window.addEventListener('scroll', () => {
        const currentScroll = window.pageYOffset;

        if (currentScroll > 100) {
            nav.style.padding = '12px 0';
            nav.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.05)';
        } else {
            nav.style.padding = '24px 0';
            nav.style.boxShadow = 'none';
        }

        lastScroll = currentScroll;
    });

    // Add hover effect to buttons
    const buttons = document.querySelectorAll('.btn');
    buttons.forEach(btn => {
        btn.addEventListener('mouseenter', function () {
            this.style.transform = 'translateY(-2px)';
        });

        btn.addEventListener('mouseleave', function () {
            this.style.transform = 'translateY(0)';
        });
    });

    // Parallax effect for hero metadata
    const heroMetadata = document.querySelector('.hero-metadata');
    if (heroMetadata) {
        window.addEventListener('scroll', () => {
            const scrolled = window.pageYOffset;
            const rate = scrolled * 0.3;
            heroMetadata.style.transform = `translateY(calc(-50% + ${rate}px)) rotate(-90deg)`;
        });
    }

    // Add cursor effect for premium feel
    const cursorDot = document.createElement('div');
    cursorDot.style.cssText = `
    position: fixed;
    width: 8px;
    height: 8px;
    background-color: black;
    border-radius: 50%;
    pointer-events: none;
    z-index: 9999;
    transition: transform 0.15s ease;
    display: none;
  `;
    document.body.appendChild(cursorDot);

    let mouseX = 0;
    let mouseY = 0;

    document.addEventListener('mousemove', (e) => {
        mouseX = e.clientX;
        mouseY = e.clientY;

        cursorDot.style.left = mouseX - 4 + 'px';
        cursorDot.style.top = mouseY - 4 + 'px';
    });

    // Show custom cursor on desktop only
    if (window.innerWidth > 768) {
        document.addEventListener('mouseenter', () => {
            cursorDot.style.display = 'block';
        });

        // Scale cursor on interactive elements
        const interactiveElements = document.querySelectorAll('a, button, .btn');
        interactiveElements.forEach(el => {
            el.addEventListener('mouseenter', () => {
                cursorDot.style.transform = 'scale(2)';
                cursorDot.style.opacity = '0.5';
            });

            el.addEventListener('mouseleave', () => {
                cursorDot.style.transform = 'scale(1)';
                cursorDot.style.opacity = '1';
            });
        });
    }

    // Add loading animation
    document.body.style.opacity = '0';
    setTimeout(() => {
        document.body.style.transition = 'opacity 0.5s ease';
        document.body.style.opacity = '1';
    }, 100);
});

// Performance optimization: Debounce scroll events
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
