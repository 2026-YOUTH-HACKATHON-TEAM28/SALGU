package com.salgu.backend.repository;

import com.salgu.backend.domain.RealEstateAgency;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RealEstateAgencyRepository extends JpaRepository<RealEstateAgency, Long> {
}
