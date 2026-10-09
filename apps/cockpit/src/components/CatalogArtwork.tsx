import { useState } from 'react';
import { catalogArt } from '@/assets/catalog-art.generated';
import { catalogArtVariants } from '@/assets/catalog-art-variants.generated';
import { safeUrl } from '@/services/business';
import type { Content } from '../../rayfin/data/schema';

export function Artwork({ film, hero = false }: {
  film: Pick<Content, 'content_key' | 'title' | 'image_url'>;
  hero?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const art = catalogArt.find(item => item.content_key === film.content_key);
  const optimized = catalogArtVariants.find(item => item.content_key === film.content_key);
  const variants = optimized?.variants;
  const display = hero ? variants?.at(-1) : variants?.[0];
  const url = art ? (failed ? art.fallback_path : display?.path ?? art.imagepath) : safeUrl(film.image_url);
  const editorial = art && (failed || art.kind === 'original-editorial');
  return url ? <div className={hero ? 'hero-art' : 'film-art'} style={{ position: hero ? 'absolute' : 'relative' }}>
    <img src={url} alt={art ? editorial ? `Illustration MSFlix for ${film.title}; not an official film poster` : art.alt : hero ? `${film.title} reference artwork` : ''}
      srcSet={!failed ? variants?.map(item => `${item.path} ${item.width}w`).join(', ') : undefined}
      sizes={hero ? '(max-width: 760px) 100vw, 75vw' : '(max-width: 600px) 90vw, (max-width: 1000px) 45vw, 320px'}
      width={display?.width} height={display?.height} decoding="async"
      loading={hero ? 'eager' : 'lazy'} fetchPriority={hero ? 'high' : 'auto'}
      onError={() => setFailed(true)} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: hero ? 'center 40%' : undefined }} />
    {editorial && <span className="editorial-credit">Illustration MSFlix · Not official artwork</span>}</div>
    : <div className={hero ? 'hero-art artwork-missing' : 'film-art artwork-missing'}
      role="img" aria-label={`Visuel non disponible : ${film.title}`}>
      <img src="/catalog-unavailable.svg" alt="" aria-hidden="true" className="unavailable-art" />
      <span>Visuel non disponible</span></div>;
}
