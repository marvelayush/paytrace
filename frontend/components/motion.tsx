"use client";

import { domAnimation, LazyMotion, m, MotionConfig, type Variants } from "motion/react";
import { useState } from "react";

/**
 * Motion for PayTrace: short (150–250 ms), ease-out, and only where it explains a change
 * (a page arriving, a list filling in, a number settling). Everything respects the OS
 * "reduce motion" setting through MotionConfig, and LazyMotion keeps the bundle small.
 */

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

export function MotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user" transition={{ duration: 0.2, ease: EASE_OUT }}>
        {children}
      </MotionConfig>
    </LazyMotion>
  );
}

// The first screen after a full page load paints at once: fading it in from opacity 0 would delay
// what the user sees and hide it from the browser's Largest Contentful Paint. Later navigations fade.
let firstScreenShown = false;

/** A screen arriving after in-app navigation: fade in and rise 4px. */
export function PageTransition({ children, className }: { children: React.ReactNode; className?: string }) {
  const [animate] = useState(() => {
    const shouldAnimate = firstScreenShown;
    firstScreenShown = true;
    return shouldAnimate;
  });
  return (
    <m.div
      className={className}
      initial={animate ? { opacity: 0, y: 4 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_OUT }}
    >
      {children}
    </m.div>
  );
}

const listVariants: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.03, delayChildren: 0.02 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 6 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.2, ease: EASE_OUT } },
};

/** A list whose items animate in once, on first load (not on every re-render). */
export function StaggerList({
  children,
  className,
  as = "ul",
  ...rest
}: { children: React.ReactNode; className?: string; as?: "ul" | "div" | "tbody" } & React.AriaAttributes & { role?: string }) {
  const Component = as === "ul" ? m.ul : as === "tbody" ? m.tbody : m.div;
  return (
    <Component className={className} variants={listVariants} initial="hidden" animate="shown" {...rest}>
      {children}
    </Component>
  );
}

export function StaggerItem({
  children,
  className,
  as = "li",
  ...rest
}: { children: React.ReactNode; className?: string; as?: "li" | "div" | "tr" } & React.AriaAttributes & { role?: string }) {
  const Component = as === "li" ? m.li : as === "tr" ? m.tr : m.div;
  return (
    <Component className={className} variants={itemVariants} {...rest}>
      {children}
    </Component>
  );
}
