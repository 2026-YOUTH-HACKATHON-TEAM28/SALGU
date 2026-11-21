package com.salgu.backend.repository;

import com.salgu.backend.domain.SubwayStation;
import org.springframework.data.jpa.repository.JpaRepository;

public interface SubwayStationRepository extends JpaRepository<SubwayStation, Long> {
}
