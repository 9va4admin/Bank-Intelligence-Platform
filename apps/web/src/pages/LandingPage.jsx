import Navbar from '../components/landing/Navbar'
import Hero from '../components/landing/Hero'
import ProblemStatement from '../components/landing/ProblemStatement'
import CTSModule from '../components/landing/CTSModule'
import EJModule from '../components/landing/EJModule'
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
        <ProblemStatement />
        <CTSModule />
        <EJModule />
        <SecuritySection />
        <Architecture />
        <TechStack />
        <ContactSection />
      </main>
      <Footer />
    </div>
  )
}
