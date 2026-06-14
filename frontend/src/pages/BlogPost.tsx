import { useEffect, useState } from 'react'
import { useParams, useNavigate, Navigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useSEO } from '../hooks/useSEO'
import { api, BlogPost as BlogPostType, BlogPostMeta } from '../api'

function formatDate(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Intl.DateTimeFormat('ar-SA', {
      year: 'numeric', month: 'long', day: 'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

// Configure marked once — async: false so we can call it synchronously.
marked.setOptions({ async: false, gfm: true, breaks: false })

function renderMarkdown(md: string): string {
  const rawHtml = marked.parse(md) as string
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
  })
}

/**
 * Inject Article JSON-LD into <head> so Google can show this article
 * in Top Stories, AI Overviews, and the standard rich result.
 */
function useArticleSchema(post: BlogPostType) {
  useEffect(() => {
    const schema = {
      '@context':        'https://schema.org',
      '@type':           'Article',
      'headline':        post.title,
      'description':     post.description,
      'datePublished':   post.published_at,
      'dateModified':    post.updated_at,
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
          'url':   'https://7ayak.app/logo.png',
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

  const [post, setPost]     = useState<BlogPostType | null>(null)
  const [related, setRelated] = useState<BlogPostMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setNotFound(false)
    Promise.all([
      api.blogGetPublic(slug),
      api.blogListPublic().then(r => r.posts).catch(() => [] as BlogPostMeta[]),
    ])
      .then(([p, all]) => {
        if (!alive) return
        setPost(p)
        const sameTagDifferentSlug = all.filter(
          (a: BlogPostMeta) => a.slug !== p.slug && a.tags.some((t: string) => p.tags.includes(t))
        ).slice(0, 2)
        setRelated(sameTagDifferentSlug)
      })
      .catch(() => { if (alive) setNotFound(true) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [slug])

  if (notFound) return <Navigate to="/blog" replace />

  // We must call useSEO/useArticleSchema unconditionally so React hook
  // ordering stays stable across renders. Use safe defaults until the
  // post loads, then they re-run with the real values.
  useSEO({
    title:       post ? `${post.title} | مدونة حياك` : 'جاري التحميل…',
    description: post?.description || '',
    canonical:   post ? `https://7ayak.app/blog/${post.slug}` : undefined,
  })
  useArticleSchema(post || {
    title: '', description: '', published_at: null, updated_at: '',
    author: '', slug: '', tags: [],
  } as unknown as BlogPostType)

  if (loading || !post) {
    return (
      <div dir="rtl" className="min-h-screen bg-white flex items-center justify-center text-slate-400">
        جاري تحميل المقال…
      </div>
    )
  }

  return (
    <div dir="rtl" className="min-h-screen bg-white text-slate-800 font-sans pb-20 overflow-x-hidden">
      <ArticleStyles />

      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-4xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/logo.png" style={{ maxWidth: '100%', height: 'auto', width: '140px' }} alt="حياك" />
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

      <article>
        <div className="max-w-3xl mx-auto px-6 pt-12 sm:pt-16 pb-8">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <div className="flex items-center gap-3 text-xs text-slate-500 mb-4">
              {post.published_at && <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>}
              {post.published_at && <span>•</span>}
              <span>{post.read_time} د قراءة</span>
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

        <div className="max-w-3xl mx-auto px-6">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.1 }}
            className="article-body"
            // Markdown is sanitized before reaching here.
            dangerouslySetInnerHTML={{ __html: renderMarkdown(post.content_md) }}
          />
        </div>

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

        {related.length > 0 && (
          <div className="max-w-3xl mx-auto px-6 mt-16">
            <h3 className="text-xl font-black text-slate-900 mb-5">مقالات ذات صلة</h3>
            <div className="grid sm:grid-cols-2 gap-4">
              {related.map(p => (
                <button
                  key={p.id}
                  onClick={() => { navigate(`/blog/${p.slug}`); window.scrollTo(0, 0) }}
                  className="text-right p-5 bg-slate-50 border border-slate-200 rounded-2xl hover:border-teal-300 hover:bg-white transition-all"
                >
                  <div className="text-xs text-slate-500 mb-2">{formatDate(p.published_at)}</div>
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

/**
 * Scoped article typography — we don't have @tailwindcss/typography
 * installed, so emulate `prose` with a <style> block. RTL-aware.
 */
function ArticleStyles() {
  return (
    <style>{`
      .article-body { color: #334155; font-size: 1.05rem; line-height: 2; }
      .article-body > *:first-child { margin-top: 0; }
      .article-body p { margin: 1.1rem 0; }
      .article-body h2 { font-size: 1.85rem; font-weight: 900; color: #0f172a; margin-top: 3rem; margin-bottom: 1rem; line-height: 1.3; }
      .article-body h3 { font-size: 1.3rem; font-weight: 800; color: #0f172a; margin-top: 2rem; margin-bottom: .75rem; line-height: 1.4; }
      .article-body strong { color: #0f172a; font-weight: 700; }
      .article-body a { color: #0d9488; font-weight: 700; text-decoration: none; border-bottom: 1px dashed #5eead4; }
      .article-body a:hover { border-bottom-style: solid; color: #0f766e; }
      .article-body ul, .article-body ol { margin: 1rem 0; padding-right: 1.5rem; }
      .article-body li { margin: .4rem 0; line-height: 2; }
      .article-body ul li { list-style: disc; }
      .article-body ol li { list-style: decimal; }
      .article-body code { color: #0f766e; background: #ccfbf1; padding: 2px 8px; border-radius: 4px; font-size: .9em; font-family: ui-monospace, monospace; direction: ltr; display: inline-block; }
      .article-body pre { background: #0f172a; color: #f1f5f9; padding: 1rem; border-radius: 8px; overflow-x: auto; direction: ltr; }
      .article-body pre code { background: transparent; color: inherit; padding: 0; }
      .article-body blockquote { margin: 1.5rem 0; padding: 1rem 1.25rem; background: #f0fdfa; border-right: 4px solid #14b8a6; border-radius: 6px; color: #134e4a; font-style: italic; }
      .article-body blockquote p { margin: 0; }
      .article-body hr { margin: 2rem 0; border: none; border-top: 1px solid #e2e8f0; }
      .article-body img { max-width: 100%; border-radius: 8px; margin: 1rem 0; }
    `}</style>
  )
}
