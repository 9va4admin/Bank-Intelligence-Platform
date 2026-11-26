import Navbar from '../components/landing/Navbar'
import Hero from '../components/landing/Hero'
import Buckets from '../components/landing/Buckets'
import WhyNow from '../components/landing/WhyNow'
import AIByDesign from '../components/landing/AIByDesign'
import ScaleNoHype from '../components/landing/ScaleNoHype'
import PlatformLayers from '../components/landing/PlatformLayers'
import Products from '../components/landing/Products'
import CTSModule from '../components/landing/CTSModule'
import SecuritySection from '../components/landing/SecuritySection'
import TechStack from '../components/landing/TechStack'
import { DashedDivider } from '../components/landing/ui'
import ContactSection from '../components/landing/ContactSection'
import Footer from '../components/landing/Footer'

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-800">
      <Navbar />
      <main>
        <Hero />
        <Buckets />
        <DashedDivider className="bg-white pb-1" />
        <WhyNow />
        <DashedDivider className="bg-white pb-1" />
        <AIByDesign />
        <DashedDivider className="bg-white pb-1" />
        <ScaleNoHype />
        <DashedDivider className="bg-white pb-1" />
        <PlatformLayers />
        <DashedDivider className="bg-white pb-1" />
        <Products />
        <DashedDivider className="bg-white pb-1" />
        <CTSModule />
        <DashedDivider className="bg-white pb-1" />
        <SecuritySection />
        <DashedDivider className="bg-white pb-1" />
        <TechStack />
        <ContactSection />
      </main>
      <Footer />
    </div>
  )
}
