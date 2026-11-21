package com.salgu.backend.repository;

import com.salgu.backend.domain.MultifamilyRental;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MultifamilyRentalRepository extends JpaRepository<MultifamilyRental, Long> {
}
