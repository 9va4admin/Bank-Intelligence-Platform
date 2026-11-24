import Navbar from '../components/landing/Navbar'
import Hero from '../components/landing/Hero'
import Buckets from '../components/landing/Buckets'
import PlatformLayers from '../components/landing/PlatformLayers'
import Products from '../components/landing/Products'
import CTSModule from '../components/landing/CTSModule'
import SecuritySection from '../components/landing/SecuritySection'
import Architecture from '../components/landing/Architecture'
import TechStack from '../components/landing/TechStack'
import ContactSection from '../components/landing/ContactSection'
import Footer from '../components/landing/Footer'

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-800">
      <Navbar />
      <main>
        <Hero />
        <Buckets />
        <PlatformLayers />
        <Products />
        <CTSModule />
        <SecuritySection />
        <Architecture />
        <TechStack />
        <ContactSection />
      </main>
      <Footer />
    </div>
  )
}
