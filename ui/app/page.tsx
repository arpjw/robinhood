import Header from '@/components/Header'
import HeroSection from '@/components/HeroSection'
import SignalSection from '@/components/SignalSection'
import ArchitectureSection from '@/components/ArchitectureSection'
import StackSection from '@/components/StackSection'
import StatusSection from '@/components/StatusSection'
import Footer from '@/components/Footer'

export default function Page() {
  return (
    <>
      <Header />
      <main style={{ paddingTop: '52px' }}>
        <HeroSection />
        <SignalSection />
        <ArchitectureSection />
        <StackSection />
        <StatusSection />
      </main>
      <Footer />
    </>
  )
}
