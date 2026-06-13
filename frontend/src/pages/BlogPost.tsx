import { useEffect } from 'react'
import { useParams, useNavigate, Navigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useSEO } from '../hooks/useSEO'
import { POSTS, POST_CONTENT } from '../content/blog/posts'

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('ar-SA', {
      year: 'numeric', month: 'long', day: 'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

/**
 * Inject Article JSON-LD into <head> so Google can show this article
 * in Top Stories, AI Overviews, and the standard rich result. Removed
 * on unmount so the next page doesn't inherit it.
 */
function useArticleSchema(post: typeof POSTS[number]) {
  useEffect(() => {
    const schema = {
      '@context':        'https://schema.org',
      '@type':           'Article',
      'headline':        post.title,
      'description':     post.description,
      'datePublished':   post.date,
      'dateModified':    post.date,
      'author': {
        '@type': 'Organization',
        'name':  post.author || 'حياك',
        'url':   'https://7ayak.app',
      },
      'publisher': {
        '@type': 'Organization',
        'name':  'حياك',
        'logo': {
          '@type': 'ImageObject',
          'url':   'https://7ayak.app/uploads/logo.png',
        },
      },
      'mainEntityOfPage': {
        '@type': 'WebPage',
        '@id':   `https://7ayak.app/blog/${post.slug}`,
      },
      'inLanguage': 'ar',
      'keywords':   post.tags.join(', '),
    }

    const el = document.createElement('script')
    el.type = 'application/ld+json'
    el.id   = 'blog-article-schema'
    el.textContent = JSON.stringify(schema)
    document.head.appendChild(el)

    return () => {
      const existing = document.getElementById('blog-article-schema')
      if (existing) existing.remove()
    }
  }, [post])
}

export default function BlogPost() {
  const { slug = '' } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  const post = POSTS.find(p => p.slug === slug)
  const Content = POST_CONTENT[slug]

  if (!post || !Content) {
    return <Navigate to="/blog" replace />
  }

  useSEO({
    title:       `${post.title} | مدونة حياك`,
    description: post.description,
    canonical:   `https://7ayak.app/blog/${post.slug}`,
  })
  useArticleSchema(post)

  // Up to 2 related posts (other articles that share at least one tag).
  const related = POSTS
    .filter(p => p.slug !== post.slug && p.tags.some(t => post.tags.includes(t)))
    .slice(0, 2)

  return (
    <div dir="rtl" className="min-h-screen bg-white text-slate-800 font-sans pb-20 overflow-x-hidden">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-4xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/uploads/logo.png" style={{ maxWidth: '100%', height: 'auto', width: '140px' }} alt="حياك" />
          </a>
          <button
            onClick={() => navigate('/blog')}
            className="inline-flex items-center gap-2 text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-5 py-2 hover:border-teal-300 hover:text-teal-600 shadow-sm transition-all"
          >
            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="rotate-180">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
            كل المقالات
          </button>
        </nav>
      </header>

      {/* Article header */}
      <article>
        <div className="max-w-3xl mx-auto px-6 pt-12 sm:pt-16 pb-8">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <div className="flex items-center gap-3 text-xs text-slate-500 mb-4">
              <time dateTime={post.date}>{formatDate(post.date)}</time>
              <span>•</span>
              <span>{post.readTime} د قراءة</span>
              <span>•</span>
              <span>بواسطة {post.author || 'حياك'}</span>
            </div>
            <h1 className="text-3xl sm:text-5xl font-black text-slate-900 leading-tight">
              {post.title}
            </h1>
            <div className="mt-5 flex flex-wrap gap-2">
              {post.tags.map(tag => (
                <span key={tag} className="text-xs font-bold text-teal-700 bg-teal-50 border border-teal-100 px-2.5 py-1 rounded-full">
                  {tag}
                </span>
              ))}
            </div>
          </motion.div>
        </div>

        {/* Article body */}
        <div className="max-w-3xl mx-auto px-6">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.1 }}>
            <Content />
          </motion.div>
        </div>

        {/* CTA */}
        <div className="max-w-3xl mx-auto px-6 mt-16">
          <div className="rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-500 px-7 py-10 text-center text-white">
            <h3 className="text-2xl font-black">جاهز تجرب حياك على متجرك؟</h3>
            <p className="mt-2 text-teal-50">ابدأ مجاناً ووصّل بوت ذكي بمتجر سلة في دقائق.</p>
            <button
              onClick={() => navigate('/landing')}
              className="mt-5 inline-flex items-center gap-2 text-base font-black text-teal-600 bg-white rounded-full px-7 py-3.5 shadow-xl hover:-translate-y-0.5 transition-transform"
            >
              ابدأ مجاناً
              <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="rotate-180">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>

        {/* Related posts */}
        {related.length > 0 && (
          <div className="max-w-3xl mx-auto px-6 mt-16">
            <h3 className="text-xl font-black text-slate-900 mb-5">مقالات ذات صلة</h3>
            <div className="grid sm:grid-cols-2 gap-4">
              {related.map(p => (
                <button
                  key={p.slug}
                  onClick={() => { navigate(`/blog/${p.slug}`); window.scrollTo(0, 0) }}
                  className="text-right p-5 bg-slate-50 border border-slate-200 rounded-2xl hover:border-teal-300 hover:bg-white transition-all"
                >
                  <div className="text-xs text-slate-500 mb-2">{formatDate(p.date)}</div>
                  <h4 className="font-bold text-slate-900 leading-snug">{p.title}</h4>
                </button>
              ))}
            </div>
          </div>
        )}
      </article>
    </div>
  )
}
